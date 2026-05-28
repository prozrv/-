import math
import queue
import ftd2xx
import time
from DB import CommandDB
import random
from collections import deque
from datetime import datetime
import threading
from typing import List, Dict, Callable, Optional

class SPI_FT4232H:
    def __init__(self, device_index=0, frequency_hz=1_000_000, db_path="commands.db"):
        self.dev = ftd2xx.open(device_index)
        self.frequency_hz = frequency_hz
        self.db_path = db_path
        
        # Потоковая передача данных
        self.streaming = False
        self.stream_thread = None
        self.data_queue = queue.Queue(maxsize=10000)  # Ограниченная очередь
        self.callback = None
        self.rx_buffer_size = 65536  # 64KB буфер для чтения
        
        self._init_spi()
        self._init_command_db()
    
    def _init_spi(self):
        """Инициализация SPI (существующий код)"""
        self.dev.resetDevice()
        self.dev.setTimeouts(5000, 5000)
        self.dev.setLatencyTimer(16)
        self.dev.setBitMode(0, 0)
        self.dev.setBitMode(0, 2)
        
        time.sleep(0.05)
        
        # Синхронизация MPSSE
        self.dev.write(b'\xAA')
        time.sleep(0.01)
        try:
            self.dev.read(2)
        except Exception:
            pass
        
        # Установка делителя частоты
        divisor = int((60_000_000 / (2 * self.frequency_hz)) - 1)
        self.dev.write(b'\x86' + bytes([divisor & 0xFF, (divisor >> 8) & 0xFF]))
        
        # Настройка пинов
        direction = 0x0B
        value = 0x08
        self.dev.write(b'\x80' + bytes([value, direction]))
    
    def start_streaming(self, callback: Callable = None, buffer_size: int = 10000):
        """
        Запуск непрерывного потока сбора данных
        
        Args:
            callback: функция обратного вызова при получении данных
            buffer_size: размер кольцевого буфера
        """
        if self.streaming:
            print("Поток уже запущен")
            return
        
        self.streaming = True
        self.callback = callback
        self.data_queue = queue.Queue(maxsize=buffer_size)
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()
        
        print(f"✓ Поток сбора данных запущен (частота: {self.frequency_hz} Гц)")
    
    def _stream_loop(self):
        """Цикл непрерывного чтения данных"""
        last_debug_time = time.time()
        frames_read = 0
        
        while self.streaming:
            try:
                # Неблокирующая проверка наличия данных в FIFO чипа
                rx_queue = self.dev.getQueueStatus()
                
                if rx_queue > 0:
                    # Читаем все доступные данные
                    bytes_to_read = min(rx_queue, self.rx_buffer_size)
                    data = self.dev.read(bytes_to_read)
                    
                    # Помещаем в очередь для потребителя
                    try:
                        self.data_queue.put(data, block=False)
                        
                        # Уведомляем GUI через callback (если нужно)
                        if self.callback:
                            self.callback(data)
                        
                        frames_read += 1
                    except queue.Full:
                        print("⚠️ Очередь данных переполнена! Потеря кадра")
                
                # Небольшая задержка для снижения нагрузки CPU
                # при отсутствии данных (1 мс - достаточно)
                if rx_queue == 0:
                    time.sleep(0.001)  # 1 мс
                    
            except Exception as e:
                print(f"Ошибка в потоке сбора данных: {e}")
                time.sleep(0.01)
    
    def read_streaming_data(self, timeout: float = 0.01) -> Optional[bytes]:
        """
        Получить данные из очереди (неблокирующий вызов для GUI)
        
        Returns:
            bytes: полученные данные или None, если данных нет
        """
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return None
    
    def stop_streaming(self):
        """Остановка потока сбора данных"""
        self.streaming = False
        if self.stream_thread:
            self.stream_thread.join(timeout=2.0)
        print("✓ Поток сбора данных остановлен")

    

    def _set_cs(self, level: int):
        """level: 0 = CS low (active), 1 = CS high (inactive)"""
        direction = 0x0B
        value = 0x08 if level else 0x00
        self.dev.write(b'\x80' + bytes([value, direction]))

    def transfer(self, out_data, read_len=0):
        """Низкоуровневый SPI-трансфер (MPSSE: write + optional read)."""
        self._set_cs(0)
        time.sleep(0.001)

        # Команда записи (0x11) — длина указывается как N-1
        length = len(out_data) - 1
        write_cmd = b'\x11' + bytes([length & 0xFF, (length >> 8) & 0xFF]) + bytes(out_data)

        # Команда чтения (0x20), если нужно читать
        read_cmd = b''
        if read_len > 0:
            read_cmd = b'\x20' + bytes([(read_len - 1) & 0xFF, ((read_len - 1) >> 8) & 0xFF])

        # Отправляем команду
        self.dev.write(write_cmd + read_cmd)
        time.sleep(0.001)

        # При необходимости читаем ответ
        response = self.dev.read(read_len) if read_len > 0 else b''

        self._set_cs(1)
        time.sleep(0.001)

        # Упрощаем возвращаемое значение
        if read_len == 0:
            return None
        elif read_len == 1:
            return response[0]
        else:
            return list(response)

    def execute_command(self, name, params=None):

        cmd = self.db.get_command_by_name(name)

        code = cmd["code"]
        tx_len = cmd["tx_len"]
        rx_len = cmd["rx_len"]

        out_data = [code]

        # Добавляем параметры, если они есть
        if params:
            out_data.extend(params[:tx_len - 1])

        return self.transfer(out_data, read_len=rx_len)


    def write_register(self, address, value):
        return self.execute_command("write_register", [address, value])
    
    def write_system_register(self, address, value):
        # Разделить на байты
        low_byte = value & 0xFF
        high_byte = (value >> 8) & 0xFF

        # Записать в регистры 0B, 0C, 0D
        self.write_register(0x0B, low_byte)
        self.write_register(0x0C, high_byte)
        self.write_register(0x0D, address)

        # Отправить команду 0x20
        return self.execute_command("spi_cmd_write_system_reg")

    def read(self, address):
        return self.execute_command("read_register", [address])
    
    def read_system_register(self, address):
        
        # Установить адрес системного регистра
        self.write_register(0x0D, address)

        # Отправить команду 0x21
        self.execute_command("spi_cmd_read_system_reg")

        # Прочитать low и high байты из 0x0B и 0x0C
        low_byte = self.read(0x0B)
        high_byte = self.read(0x0C)

        if low_byte is None or high_byte is None:
            raise Exception("Ошибка чтения системного регистра")

        value = (high_byte << 8) | low_byte

        return value
    
    def list_available_commands(self):
        return self.db.list_commands()

    def close(self):
        self.db.close()
        self.dev.close()



class SPIStub:
    """
    Заглушка для SPI устройства - простая версия
    """
    
    def __init__(self, device_index=0, frequency_hz=1_000_000, db_path="commands.db", real_mode=False):
        self.device_index = device_index
        self.frequency_hz = frequency_hz
        self.is_open = True
        self.real_mode = real_mode
        
        # Регистры устройства
        self.registers = {}
        self.system_registers = {}
        
        # Монитор (будет создан позже)
        self.monitor = None
        
        # Генерация тестовых данных
        self.test_mode = "sine"
        self.test_phase = 0
        self.test_amplitude = 127
        self.test_offset = 127
        
        self._init_registers()
        self._init_system_registers()
        
        mode_str = "реальном" if real_mode else "тестовом"
        print(f"✓ Заглушка SPI инициализирована в {mode_str} режиме")
    
    def _init_registers(self):
        """Инициализация стандартных регистров"""
        self.registers[0x0B] = 0x00
        self.registers[0x0C] = 0x00
        self.registers[0x0D] = 0x00
        
        for i in range(256):
            if i not in self.registers:
                self.registers[i] = 0x00
    
    def _init_system_registers(self):
        """Инициализация системных регистров"""
        for i in range(0x1C, 0x48):
            self.system_registers[i] = 0x0000
    
    def set_monitor(self, monitor):
        """Установить монитор для получения данных"""
        self.monitor = monitor
        print("✓ Монитор подключен к устройству")
    
    def write_register(self, address: int, value: int, silent: bool = False) -> bool:
        """Запись в регистр"""
        if not (0 <= address <= 255):
            raise ValueError(f"Адрес должен быть 0-255, получен {address}")
        if not (0 <= value <= 255):
            raise ValueError(f"Значение должно быть 0-255, получен {value}")
        
        self.registers[address] = value
        
        # Отправляем в монитор, если он есть
        if self.monitor:
            self.monitor.add_data_point(address, value)
            if not silent:
                print(f"📊 Отправлено в монитор: 0x{address:02X} = {value}")
        
        if not silent:
            mode = "РЕАЛЬНЫЙ" if self.real_mode else "ТЕСТОВЫЙ"
            print(f"✓ [{mode}] Запись 0x{address:02X} = 0x{value:02X} ({value})")
        
        time.sleep(0.0005)
        return True
    
    def read(self, address: int, silent: bool = False) -> int:
        """Чтение из регистра"""
        if not (0 <= address <= 255):
            raise ValueError(f"Адрес должен быть 0-255, получен {address}")
        
        value = self.registers.get(address, 0)
        
        if not silent:
            mode = "РЕАЛЬНЫЙ" if self.real_mode else "ТЕСТОВЫЙ"
            print(f"✓ [{mode}] Чтение 0x{address:02X} = 0x{value:02X} ({value})")
        
        return value
    
    def write_system_register(self, address: int, value: int) -> None:
        """Запись в системный регистр"""
        if not (0x1C <= address <= 0x47):
            raise ValueError(f"Адрес должен быть 0x1C-0x47, получен {address}")
        
        self.system_registers[address] = value
        print(f"✓ Системная запись 0x{address:02X} = 0x{value:04X}")
        
        self.registers[0x0B] = value & 0xFF
        self.registers[0x0C] = (value >> 8) & 0xFF
        self.registers[0x0D] = address
    
    def read_system_register(self, address: int) -> int:
        """Чтение из системного регистра"""
        if not (0x1C <= address <= 0x47):
            raise ValueError(f"Адрес должен быть 0x1C-0x47, получен {address}")
        
        value = self.system_registers.get(address, 0)
        print(f"✓ Системное чтение 0x{address:02X} = 0x{value:04X}")
        
        self.registers[0x0B] = value & 0xFF
        self.registers[0x0C] = (value >> 8) & 0xFF
        self.registers[0x0D] = address
        
        return value
    
    def start_monitoring(self, address: int, callback=None, history_size: int = 100):
        """Начать мониторинг регистра"""
        from register_monitor import RegisterMonitor
        
        # Создаем монитор, если его нет
        if not self.monitor:
            self.monitor = RegisterMonitor(self, None)
        
        # Запускаем мониторинг
        self.monitor.start_monitoring(address, time_window=10.0)
        print(f"✓ Мониторинг регистра 0x{address:02X} запущен")
        
        return self.monitor
    
    def generate_test_data(self, address: int, pattern: str = "sine", 
                          duration: float = 5.0, amplitude: int = 100, offset: int = 128):
        """
        Генерация тестовых данных в регистр
        """
        print(f"📊 Генерация {pattern} сигнала в регистр 0x{address:02X}")
        print(f"   Амплитуда: {amplitude}, смещение: {offset}, длительность: {duration} сек")
        
        num_points = int(duration * 100)  # 100 точек в секунду
        
        for i in range(num_points):
            t = i / 100.0
            
            if pattern == "sine":
                value = offset + amplitude * math.sin(2 * math.pi * 0.5 * t)
            elif pattern == "step":
                step = int(t * 2) % 8
                value = offset - amplitude + step * (2 * amplitude / 7)
            elif pattern == "ramp":
                value = offset - amplitude + (t % 2) * (2 * amplitude)
            elif pattern == "square":
                value = offset + amplitude if int(t * 2) % 2 == 0 else offset - amplitude
            else:
                value = offset
            
            value = int(max(0, min(255, value)))
            self.write_register(address, value, silent=False)  # silent=False для отладки
            time.sleep(0.01)  # 10 мс между точками
            
            # Прогресс
            if (i + 1) % 50 == 0:
                print(f"   Прогресс: {i+1}/{num_points} ({int((i+1)*100/num_points)}%)")
        
        print(f"✓ Генерация завершена")
    
    def close(self):
        """Закрытие устройства"""
        if self.monitor:
            self.monitor.close_all()
        self.is_open = False
        print("✓ Устройство закрыто")
    
    # Методы-заглушки для совместимости
    def _init_spi(self):
        pass
    
    def _set_cs(self, level: int):
        pass
    
    def transfer(self, out_data, read_len=0):
        pass
    
    def execute_command(self, name, params=None):
        pass
    
    def list_available_commands(self):
        return []

def main():
    spi = SPI_FT4232H()

    print("📋 Доступные команды:")
    for name, code, tx, rx, desc in spi.list_available_commands():
        print(f"  {name:15s}  code=0x{code:02X}, tx={tx}, rx={rx}  — {desc}")

    print("\n➡ Записываем 0x12 в регистр 0x18...")
    spi.write_register(0x18, 0x12)
    time.sleep(0.5)

    print("➡ Читаем регистр 0x18...")
    val = spi.read(0x18)
    print(f"Получено значение: 0x{val:02X}" if val is not None else "Ошибка чтения")

    spi.close()


if __name__ == "__main__":
    main()
