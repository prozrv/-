import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import time
import numpy as np
from typing import List, Dict, Optional

class RegisterMonitor:
    """
    Потребитель данных для визуализации в реальном времени
    - Простые буферы без сложных блокировок
    - Статическое окно времени
    """
    
    def __init__(self, spi_device, root=None, update_interval_ms: int = 100):
        self.spi = spi_device
        self.root = root
        self.update_interval = update_interval_ms / 1000.0  # в секундах
        
        # Простые буферы для каждого регистра (адрес -> список точек)
        self.data_buffers = {}  # address -> list of (timestamp, value)
        self.buffer_sizes = {}  # address -> max size
        self.plot_windows = {}  # address -> (fig, ax, line, info_text)
        
        # Флаг работы
        self.running = True
        
        # Запускаем периодическое обновление в главном потоке
        if self.root:
            self._schedule_updates()
    
    def start_monitoring(self, address: int, time_window: float = 10.0, buffer_size: int = 50000):
        """
        Начать мониторинг регистра
        
        Args:
            address: адрес регистра
            time_window: отображаемый период времени (секунды)
            buffer_size: максимальный размер буфера
        """
        if address in self.data_buffers:
            print(f"Мониторинг 0x{address:02X} уже запущен")
            return
        
        # Создаем буфер
        self.data_buffers[address] = []  # список для хранения (timestamp, value)
        self.buffer_sizes[address] = buffer_size
        
        # Создаем окно графика
        self._create_plot_window(address, time_window)
        
        print(f"✓ Мониторинг регистра 0x{address:02X} запущен")
    
    def add_data_point(self, address: int, value: int):
        """
        Добавить точку данных в буфер (вызывается из потока Producer)
        Этот метод максимально быстрый
        """
        if address not in self.data_buffers:
            return
        
        timestamp = time.time()
        buffer = self.data_buffers[address]
        
        # Просто добавляем точку
        buffer.append((timestamp, value))
        
        # Ограничиваем размер буфера (только при превышении лимита)
        if len(buffer) > self.buffer_sizes[address]:
            # Удаляем половину буфера для эффективности
            trim_size = self.buffer_sizes[address] // 2
            self.data_buffers[address] = buffer[-trim_size:]
    
    def add_data_batch(self, address: int, batch: List[int]):
        """
        Добавить пачку данных (для высокой частоты)
        
        Args:
            address: адрес регистра
            batch: список значений
        """
        if address not in self.data_buffers:
            return
        
        timestamp = time.time()
        buffer = self.data_buffers[address]
        
        # Добавляем пачку с одним временем (или с интервалом)
        interval = 1.0 / 1000  # предполагаем 1000 Гц, можно настроить
        for i, value in enumerate(batch):
            buffer.append((timestamp + i * interval, value))
        
        # Ограничиваем размер буфера
        if len(buffer) > self.buffer_sizes[address]:
            trim_size = self.buffer_sizes[address] // 2
            self.data_buffers[address] = buffer[-trim_size:]
    
    def _create_plot_window(self, address: int, time_window: float):
        """Создание окна графика в главном потоке"""
        if self.root:
            self.root.after(0, lambda: self._create_plot_in_main_thread(address, time_window))
        else:
            self._create_plot_in_main_thread(address, time_window)
    
    def _create_plot_in_main_thread(self, address: int, time_window: float):
        """Создание окна в главном потоке"""
        fig, ax = plt.subplots(figsize=(12, 6))
        fig.canvas.manager.set_window_title(f"Мониторинг регистра 0x{address:02X}")
        
        line, = ax.plot([], [], 'b-', linewidth=1.5)
        ax.set_xlabel('Время (секунды)')
        ax.set_ylabel('Значение')
        ax.set_title(f'Регистр 0x{address:02X} (окно: {time_window} сек)')
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 255)
        ax.set_xlim(0, time_window)
        
        # Текст с информацией
        info_text = ax.text(0.02, 0.95, '', transform=ax.transAxes, fontsize=10,
                           verticalalignment='top',
                           bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        # Сохраняем данные окна
        self.plot_windows[address] = {
            'fig': fig,
            'ax': ax,
            'line': line,
            'info_text': info_text,
            'time_window': time_window
        }
        
        # Запускаем циклическое обновление для этого окна
        self._start_plot_updates(address)
        
        # Обработчик закрытия окна
        def on_close(event):
            self.stop_monitoring(address)
        
        fig.canvas.mpl_connect('close_event', on_close)
        plt.show(block=False)
    
    def _start_plot_updates(self, address: int):
        """Запуск периодического обновления графика"""
        def update_plot():
            if not self.running:
                return
            
            if address not in self.plot_windows:
                return
            
            if address not in self.data_buffers:
                # Если буфер удален, закрываем окно
                if address in self.plot_windows:
                    plt.close(self.plot_windows[address]['fig'])
                    del self.plot_windows[address]
                return
            
            buffer = self.data_buffers[address]
            plot_info = self.plot_windows[address]
            
            if buffer:
                current_time = time.time()
                cutoff_time = current_time - plot_info['time_window']
                
                # Фильтруем данные по времени
                filtered = [(ts - cutoff_time, val) for ts, val in buffer if ts >= cutoff_time]
                
                if filtered:
                    times = [ts for ts, _ in filtered]
                    values = [val for _, val in filtered]
                    
                    plot_info['line'].set_data(times, values)
                    
                    # Автомасштабирование Y
                    if values:
                        y_min = min(values)
                        y_max = max(values)
                        y_range = y_max - y_min
                        plot_info['ax'].set_ylim(
                            max(0, y_min - y_range * 0.1),
                            min(255, y_max + y_range * 0.1)
                        )
                    
                    # Обновляем информацию
                    current_value = values[-1]
                    avg_value = np.mean(values) if values else 0
                    
                    plot_info['info_text'].set_text(
                        f"Регистр: 0x{address:02X}\n"
                        f"Текущее: {current_value} (0x{int(current_value):02X})\n"
                        f"Среднее: {avg_value:.1f}\n"
                        f"Точек: {len(filtered)}"
                    )
                    
                    plot_info['ax'].relim()
                    plot_info['fig'].canvas.draw_idle()
            
            # Планируем следующее обновление
            if self.root and self.running and address in self.plot_windows:
                self.root.after(int(self.update_interval * 1000), update_plot)
        
        if self.root:
            self.root.after(int(self.update_interval * 1000), update_plot)
    
    def stop_monitoring(self, address: int = None):
        """Остановка мониторинга"""
        try:
            if address is None:
                addresses = list(self.data_buffers.keys())
                for addr in addresses:
                    self._close_monitor(addr)
            elif address in self.data_buffers:
                self._close_monitor(address)
        except Exception as e:
            print(f"Ошибка при остановке: {e}")
    
    def _close_monitor(self, address: int):
        """Закрыть монитор"""
        try:
            # Закрываем окно
            if address in self.plot_windows:
                try:
                    plt.close(self.plot_windows[address]['fig'])
                except:
                    pass
                del self.plot_windows[address]
            
            # Удаляем буфер
            if address in self.data_buffers:
                del self.data_buffers[address]
            if address in self.buffer_sizes:
                del self.buffer_sizes[address]
            
            print(f"✓ Мониторинг регистра 0x{address:02X} остановлен")
        except Exception as e:
            print(f"Ошибка при закрытии: {e}")
    
    def _schedule_updates(self):
        """Периодическое обновление (для совместимости)"""
        if self.root and self.running:
            self.root.after(int(self.update_interval * 1000), self._schedule_updates)
    
    def get_active_monitors(self) -> List[int]:
        """Получить список активных мониторов"""
        return list(self.data_buffers.keys())
    
    def close_all(self):
        """Закрыть все мониторы"""
        self.running = False
        self.stop_monitoring()
        print("✓ Все мониторы закрыты")