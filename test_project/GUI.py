import math
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import queue
import time
import threading
from spi_ft4232h3 import SPI_FT4232H, SPIStub
from register_monitor import RegisterMonitor

class SPIHandler:
    """
    Класс-прослойка для преобразования данных с GUI
    и работы с SPI устройством (реальным или заглушкой)
    """
    
    def __init__(self, use_stub=True):
        self.device = None
        self.use_stub = use_stub
        self.is_running = False
        self.data_queue = queue.Queue()
        self.monitor = None
        
    def open_device(self, device_index=0, frequency_hz=1000000, use_stub=True, real_mode=False):
        """Открытие устройства (реального или заглушки)"""
        try:
            if use_stub:
                self.device = SPIStub(device_index, frequency_hz, real_mode=real_mode)
            else:
                self.device = SPI_FT4232H(device_index, frequency_hz)
                
            self.data_queue.put(('status', f"Устройство {device_index} открыто"))
            self.data_queue.put(('status', f"Частота: {frequency_hz} Гц"))
            self.use_stub = use_stub
            return True
            
        except Exception as e:
            self.data_queue.put(('error', f"Ошибка открытия устройства: {str(e)}"))
            return False
    
    def close_device(self):
        """Закрытие устройства"""
        if self.monitor:
            self.monitor.close_all_windows()
        if self.device:
            self.device.close()
            self.device = None
            self.monitor = None
            self.data_queue.put(('status', "Устройство закрыто"))
        
    def write_register(self, address, value):
        """Запись в регистр"""
        if not self.device:
            raise Exception("Устройство не открыто")
        
        result = self.device.write_register(address, value)
        self.data_queue.put(('status', 
                           f"Запись: регистр 0x{address:02X} = 0x{value:02X} ({value})"))
        return result
    
    def write_system_register(self, address, value):
        """Запись в 16-битный системный регистр"""
        if not self.device:
            raise Exception("Устройство не открыто")
        
        self.device.write_system_register(address, value)
        self.data_queue.put(('status', f"Системная запись: [0x{address:02X}] = 0x{value:04X}"))

    def read_system_register(self, address):
        """Чтение из 16-битного системного регистра"""
        if not self.device:
            raise Exception("Устройство не открыто")

        value = self.device.read_system_register(address)
        self.data_queue.put(('status', f"Системное чтение: [0x{address:02X}] = 0x{value:04X}"))
        return value

    def read_register(self, address):
        """Чтение регистра"""
        if not self.device:
            raise Exception("Устройство не открыто")
        value = self.device.read(address)
        if value is not None:
            self.data_queue.put(('status', 
                               f"Чтение: регистр 0x{address:02X} = 0x{value:02X} ({value})"))
        return value

class SPIApp:
    """GUI приложение для работы с SPI"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("SPI Controller - Управление регистрами")
        self.root.geometry("900x700")
        
        self.spi_handler = SPIHandler()
        self.transfer_thread = None
        self.active_monitors = {}
        
        self.create_widgets()
        self.update_queue()
        self.on_operation_change("Запись 8-битного регистра")
        self.modified_sysregs = set()

    def on_device_type_changed(self, event=None):
        """Обработчик изменения выбора устройства"""
        device_type = self.device_type_var.get()
        is_stub = device_type.startswith("stub")
        
        # Показываем/скрываем кнопку генерации тестовых данных
        if is_stub:
            self.generate_btn.grid()
        else:
            self.generate_btn.grid_remove()

    def create_widgets(self):
        """Создание элементов интерфейса"""
        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Настройки растягивания
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # === Секция подключения ===
        conn_frame = ttk.LabelFrame(main_frame, text="Подключение устройства", padding="5")
        conn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        conn_frame.columnconfigure(1, weight=1)
        
                # Кнопки подключения
        ttk.Button(conn_frame, text="Подключить устройство", 
                command=self.connect_device).grid(row=0, column=0, padx=5)
        ttk.Button(conn_frame, text="Отключить устройство", 
                command=self.disconnect_device).grid(row=0, column=1, padx=5)
        
        # Выбор устройства
        ttk.Label(conn_frame, text="Выбор устройства:").grid(row=0, column=2, padx=(20, 5), sticky=tk.W)
        self.device_type_var = tk.StringVar(value="stub")
        device_combo = ttk.Combobox(conn_frame, textvariable=self.device_type_var, 
                                    values=["stub (Заглушка)", "ft4232h (Реальное устройство)"],
                                    state="readonly", width=25)
        device_combo.grid(row=0, column=3, padx=5, sticky=tk.W)
        
        # Кнопка генерации тестовых данных
        self.generate_btn = ttk.Button(conn_frame, text="Сгенерировать тестовые данные", 
                                        command=self.generate_test_data)
        self.generate_btn.grid(row=1, column=0, columnspan=2, pady=5, sticky=tk.W)
        
        # Привязываем событие изменения выбора устройства
        device_combo.bind("<<ComboboxSelected>>", self.on_device_type_changed)

        # === Секция мониторинга регистров ===
        monitor_frame = ttk.LabelFrame(main_frame, text="Мониторинг регистров", padding="5")
        monitor_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        monitor_frame.columnconfigure(1, weight=1)
        
        ttk.Label(monitor_frame, text="Регистр для мониторинга (hex):").grid(row=0, column=0, sticky=tk.W)
        self.monitor_address_var = tk.StringVar(value="10")
        monitor_entry = ttk.Entry(monitor_frame, textvariable=self.monitor_address_var, width=10)
        monitor_entry.grid(row=0, column=1, padx=5, sticky=tk.W)
        
        ttk.Label(monitor_frame, text="Размер истории:").grid(row=0, column=2, sticky=tk.W, padx=(10,0))
        self.history_size_var = tk.IntVar(value=100)
        # Заменяем Spinbox на Entry + кнопки
        history_frame = ttk.Frame(monitor_frame)
        history_frame.grid(row=0, column=3, padx=5, sticky=tk.W)
        history_entry = ttk.Entry(history_frame, textvariable=self.history_size_var, width=8)
        history_entry.pack(side=tk.LEFT)
        ttk.Button(history_frame, text="▲", command=lambda: self.history_size_var.set(min(500, self.history_size_var.get() + 10)), width=2).pack(side=tk.LEFT)
        ttk.Button(history_frame, text="▼", command=lambda: self.history_size_var.set(max(10, self.history_size_var.get() - 10)), width=2).pack(side=tk.LEFT)
        
        #ttk.Label(monitor_frame, text="Интервал (мс):").grid(row=0, column=4, sticky=tk.W, padx=(10,0))
        #self.interval_var = tk.IntVar(value=100)
        # Заменяем Spinbox на Entry + кнопки
        #interval_frame = ttk.Frame(monitor_frame)
        #interval_frame.grid(row=0, column=5, padx=5, sticky=tk.W)
        #interval_entry = ttk.Entry(interval_frame, textvariable=self.interval_var, width=8)
        #interval_entry.pack(side=tk.LEFT)
        #ttk.Button(interval_frame, text="▲", command=lambda: self.interval_var.set(min(1000, self.interval_var.get() + 50)), width=2).pack(side=tk.LEFT)
        #ttk.Button(interval_frame, text="▼", command=lambda: self.interval_var.set(max(50, self.interval_var.get() - 50)), width=2).pack(side=tk.LEFT)
        
        ttk.Button(monitor_frame, text="Начать мониторинг", 
                command=self.start_monitoring).grid(row=1, column=0, columnspan=2, pady=5, sticky=tk.W)
        ttk.Button(monitor_frame, text="Остановить все", 
                command=self.stop_all_monitoring).grid(row=1, column=2, columnspan=2, pady=5, sticky=tk.W)
        
        # Список активных мониторов
        ttk.Label(monitor_frame, text="Активные мониторы:").grid(row=2, column=0, sticky=tk.W, pady=(5,0))
        self.monitors_listbox = tk.Listbox(monitor_frame, height=4)
        self.monitors_listbox.grid(row=3, column=0, columnspan=5, sticky=(tk.W, tk.E), pady=2)
        
        # Кнопка закрытия выбранного монитора
        ttk.Button(monitor_frame, text="Закрыть выбранный", 
                command=self.stop_selected_monitoring).grid(row=3, column=5, padx=5)
        
        # === Секция выбора операции ===
        operation_frame = ttk.LabelFrame(main_frame, text="Операция", padding="5")
        operation_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        ttk.Label(operation_frame, text="Выберите операцию:").grid(row=0, column=0, sticky=tk.W)

        self.operation_var = tk.StringVar(value="write_8bit")

        operations = [
            ("Запись 8-битного регистра", "write_8bit"),
            ("Чтение 8-битного регистра", "read_8bit"),
            ("Запись 16-битного системного регистра", "write_sysreg"),
            ("Чтение 16-битного системного регистра", "read_sysreg"),
            ("Просмотр и редактирование системных регистров", "view_edit_sysregs")
        ]

        operation_names = [name for name, _ in operations]
        operation_codes = {name: code for name, code in operations}
        self.operation_codes = operation_codes

        self.operation_menu = ttk.OptionMenu(
            operation_frame,
            self.operation_var,
            operation_names[0],
            *operation_names,
            command=self.on_operation_change
        )
        self.operation_menu.grid(row=0, column=1, padx=10)

        # === Контейнер для динамического отображения полей операции ===
        self.dynamic_frame = ttk.Frame(operation_frame)
        self.dynamic_frame.grid(row=1, column=0, columnspan=2, pady=5, sticky=tk.W)
        
        self.sysreg_tree = None
        self.editing_entry = None
        
        # Лог сообщений
        log_frame = ttk.LabelFrame(main_frame, text="Лог сообщений", padding="5")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    
    def generate_test_data(self):
        """Генерация тестовых данных в регистр"""
        if not self.spi_handler.device:
            messagebox.showerror("Ошибка", "Устройство не подключено")
            return
        
        # Простой диалог без лишних сложностей
        dialog = tk.Toplevel(self.root)
        dialog.title("Генерация тестовых данных")
        dialog.geometry("350x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Адрес регистра (hex):").pack(pady=5)
        addr_var = tk.StringVar(value="10")
        ttk.Entry(dialog, textvariable=addr_var, width=10).pack()
        
        ttk.Label(dialog, text="Тип сигнала:").pack(pady=5)
        pattern_var = tk.StringVar(value="sine")
        ttk.Combobox(dialog, textvariable=pattern_var, 
                    values=["sine (синус)", "step (ступеньки)", 
                            "ramp (пила)", "square (меандр)"],
                    state="readonly").pack()
        
        ttk.Label(dialog, text="Длительность (сек):").pack(pady=5)
        duration_var = tk.DoubleVar(value=5.0)
        ttk.Spinbox(dialog, from_=1, to=30, textvariable=duration_var, width=10).pack()
        
        def start_generation():
            try:
                address = int(addr_var.get(), 16)
                pattern = pattern_var.get().split()[0]
                duration = duration_var.get()
                
                dialog.destroy()
                
                self.log_message(f"Начало генерации {pattern} сигнала в регистр 0x{address:02X}")
                
                # Запускаем в отдельном потоке, чтобы не блокировать GUI
                def generate():
                    try:
                        self.spi_handler.device.generate_test_data(
                            address, pattern, duration, amplitude=100, offset=128
                        )
                        self.root.after(0, lambda: self.log_message(f"✓ Генерация завершена"))
                    except Exception as e:
                        self.root.after(0, lambda: self.log_message(f"✗ Ошибка: {e}"))
                
                import threading
                thread = threading.Thread(target=generate, daemon=True)
                thread.start()
                
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        ttk.Button(dialog, text="Старт", command=start_generation).pack(pady=20)
    
    def start_monitoring(self):
        """Начать мониторинг"""
        if not self.spi_handler.device:
            messagebox.showerror("Ошибка", "Устройство не подключено")
            return
        
        try:
            address_str = self.monitor_address_var.get().strip()
            if address_str.startswith('0x') or address_str.startswith('0X'):
                address = int(address_str, 16)
            else:
                address = int(address_str, 16)
            
            if not (0 <= address <= 255):
                raise ValueError("Адрес должен быть 0x00-0xFF")
            
            time_window = 10.0  # 10 секунд окно
            
            # Создаем монитор, если его нет
            if not self.spi_handler.monitor:
                from register_monitor import RegisterMonitor
                self.spi_handler.monitor = RegisterMonitor(
                    self.spi_handler.device, 
                    self.root,
                    update_interval_ms=100
                )
                # Связываем монитор с устройством
                if hasattr(self.spi_handler.device, 'set_monitor'):
                    self.spi_handler.device.set_monitor(self.spi_handler.monitor)
            
            # Запускаем мониторинг регистра (без start_streaming!)
            self.spi_handler.monitor.start_monitoring(address, time_window)
            
            self.update_monitors_list()
            self.log_message(f"✓ Начат мониторинг регистра 0x{address:02X} (окно: {time_window} сек)")
            self.log_message(f"  Данные будут появляться при записи в регистр или генерации")
            
        except ValueError as e:
            messagebox.showerror("Ошибка", f"Неверный адрес регистра: {e}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось запустить мониторинг: {e}")

    def stop_selected_monitoring(self):
        """Остановить выбранный мониторинг"""
        selection = self.monitors_listbox.curselection()
        if not selection:
            messagebox.showwarning("Предупреждение", "Выберите монитор для остановки")
            return
        
        selected_text = self.monitors_listbox.get(selection[0])
        try:
            address_str = selected_text.split()[1]
            address = int(address_str, 16)
            
            if self.spi_handler.monitor:
                self.spi_handler.monitor.stop_monitoring(address)
                self.update_monitors_list()
                self.log_message(f"Остановлен мониторинг регистра 0x{address:02X}")
        except Exception as e:
            self.log_message(f"Ошибка при остановке мониторинга: {e}")
    
    def stop_all_monitoring(self):
        """Остановка всех мониторов и потока сбора"""
        if self.spi_handler.monitor:
            self.spi_handler.monitor.close_all()
        if self.spi_handler.device:
            self.spi_handler.device.stop_streaming()
        self.update_monitors_list()
        self.log_message("✓ Все потоки остановлены")
    
    def update_monitors_list(self):
        """Обновить список активных мониторов"""
        self.monitors_listbox.delete(0, tk.END)
        
        # Используем правильное имя атрибута - data_buffers
        if self.spi_handler.monitor and hasattr(self.spi_handler.monitor, 'data_buffers'):
            for address in self.spi_handler.monitor.data_buffers.keys():
                self.monitors_listbox.insert(tk.END, f"Регистр 0x{address:02X}")
    
    def log_message(self, message):
        """Добавление сообщения в лог"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        
    def update_queue(self):
        """Обновление данных из очереди"""
        try:
            while True:
                msg_type, message = self.spi_handler.data_queue.get_nowait()
                if msg_type == 'status':
                    self.log_message(f"✓ {message}")
                elif msg_type == 'error':
                    self.log_message(f"✗ {message}")
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.update_queue)
    
    def _on_data_received(self, data: bytes):
        """Колбэк при получении новых данных (вызывается из потока-воркера)"""
        # Минимальная обработка - просто логирование для отладки
        # Основная обработка в потребителе
        pass
   
    def connect_device(self):
        """Подключение к устройству"""
        try:
            device_type = self.device_type_var.get()
            use_stub = device_type.startswith("stub")
            real_mode = False  # для заглушки
            
            device_name = "Заглушке" if use_stub else "FT4232H"
            
            if self.spi_handler.open_device(use_stub=use_stub, real_mode=real_mode):
                self.log_message(f"Устройство подключено в {device_name} режиме")
                
                # Создаем монитор сразу после подключения
                if not self.spi_handler.monitor:
                    from register_monitor import RegisterMonitor
                    self.spi_handler.monitor = RegisterMonitor(
                        self.spi_handler.device, 
                        self.root,
                        update_interval_ms=100
                    )
                    # Связываем монитор с устройством
                    if hasattr(self.spi_handler.device, 'set_monitor'):
                        self.spi_handler.device.set_monitor(self.spi_handler.monitor)
                
                self.log_message("Монитор готов к работе")
                
        except Exception as e:
            messagebox.showerror("Ошибка подключения", str(e))
    
    def disconnect_device(self):
        """Отключение устройства"""
        self.spi_handler.close_device()
        self.log_message("Устройство отключено")
        self.update_monitors_list()
    
    def execute_operation(self):
        label = self.operation_var.get()
        op = self.operation_codes.get(label)

        try:
            if op == "write_8bit":
                address = int(self.reg_addr_var.get(), 16)
                value = int(self.reg_data_var.get(), 16)
                if not (0 <= address <= 255) or not (0 <= value <= 255):
                    raise ValueError("Адрес и данные должны быть 8-битными (0x00-0xFF)")
                self.spi_handler.write_register(address, value)

            elif op == "read_8bit":
                address = int(self.reg_addr_var.get(), 16)
                if not (0 <= address <= 255):
                    raise ValueError("Адрес должен быть 8-битным (0x00-0xFF)")
                value = self.spi_handler.read_register(address)
                if value is not None:
                    self.reg_data_var.set(f"{value:02X}")

            elif op == "write_sysreg":
                addr = int(self.sysreg_addr_var.get(), 16)
                val = int(self.sysreg_data_var.get(), 16)
                if not (0x1C <= addr <= 0x47):
                    raise ValueError("Адрес системного регистра должен быть в диапазоне 0x1C-0x47")
                if not (0 <= val <= 0xFFFF):
                    raise ValueError("Данные системного регистра должны быть 16-битными")
                self.spi_handler.write_system_register(addr, val)

            elif op == "read_sysreg":
                addr = int(self.sysreg_addr_var.get(), 16)
                if not (0x1C <= addr <= 0x47):
                    raise ValueError("Адрес системного регистра должен быть в диапазоне 0x1C-0x47")
                val = self.spi_handler.read_system_register(addr)
                self.sysreg_data_var.set(f"{val:04X}")
            
            elif op == "view_edit_sysregs":
                self.apply_sysreg_changes()

            else:
                self.log_message(f"Неизвестная операция: {label}")

        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def on_operation_change(self, selected_label):
        """Вызывается при изменении операции — обновляет динамические поля"""
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

        operation = self.operation_codes[selected_label]

        if operation in ("write_8bit", "read_8bit"):
            ttk.Label(self.dynamic_frame, text="Адрес регистра (hex):").grid(row=0, column=0, sticky=tk.W)
            self.reg_addr_var = tk.StringVar(value="10")
            ttk.Entry(self.dynamic_frame, textvariable=self.reg_addr_var, width=10).grid(row=0, column=1, padx=5)

            if operation == "write_8bit":
                ttk.Label(self.dynamic_frame, text="Данные (hex):").grid(row=0, column=2, sticky=tk.W)
                self.reg_data_var = tk.StringVar(value="00")
                ttk.Entry(self.dynamic_frame, textvariable=self.reg_data_var, width=10).grid(row=0, column=3, padx=5)

        elif operation in ("write_sysreg", "read_sysreg"):
            ttk.Label(self.dynamic_frame, text="Адрес системного регистра (hex 1C-47):").grid(row=0, column=0, sticky=tk.W)
            self.sysreg_addr_var = tk.StringVar(value="1C")
            ttk.Entry(self.dynamic_frame, textvariable=self.sysreg_addr_var, width=10).grid(row=0, column=1, padx=5)

            if operation == "write_sysreg":
                ttk.Label(self.dynamic_frame, text="Данные (hex 16-bit):").grid(row=0, column=2, sticky=tk.W)
                self.sysreg_data_var = tk.StringVar(value="0000")
                ttk.Entry(self.dynamic_frame, textvariable=self.sysreg_data_var, width=10).grid(row=0, column=3, padx=5)
            elif operation == "read_sysreg":
                if not hasattr(self, 'sysreg_data_var'):
                    self.sysreg_data_var = tk.StringVar(value="----")
                ttk.Label(self.dynamic_frame, text="Значение (hex):").grid(row=1, column=2, sticky=tk.W)
                ttk.Entry(self.dynamic_frame, textvariable=self.sysreg_data_var, width=10, state="readonly").grid(row=1, column=3, padx=5)

        elif operation == "view_edit_sysregs":
            self.create_sysreg_table(self.dynamic_frame)

        ttk.Button(self.dynamic_frame, text="Выполнить", command=self.execute_operation).grid(row=1, column=0, columnspan=4, pady=10, sticky=tk.W)

    def create_sysreg_table(self, parent):
        """Создает таблицу системных регистров"""
        frame = ttk.LabelFrame(parent, text="Таблица системных регистров (0x1C - 0x47)", padding=5)
        frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)

        columns = ("address", "value")
        self.sysreg_tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.sysreg_tree.heading("address", text="Адрес")
        self.sysreg_tree.heading("value", text="Значение (16-bit HEX)")
        self.sysreg_tree.column("address", width=80, anchor=tk.CENTER)
        self.sysreg_tree.column("value", width=120, anchor=tk.CENTER)
        self.sysreg_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.sysreg_tree.yview)
        self.sysreg_tree.configure(yscroll=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        for addr in range(0x1C, 0x48):
            try:
                value = self.spi_handler.read_system_register(addr)
                val_str = f"{value:04X}" if value is not None else "----"
            except Exception as e:
                val_str = "ERR"
                self.log_message(f"✗ Ошибка чтения регистра 0x{addr:02X}: {e}")
            self.sysreg_tree.insert("", tk.END, values=(f"0x{addr:02X}", val_str))

        self.editing_entry = None
        self.sysreg_tree.bind("<Double-1>", self.on_double_click_sysreg)

        apply_btn = ttk.Button(frame, text="Применить изменения", command=self.apply_sysreg_changes)
        apply_btn.grid(row=1, column=0, pady=5, sticky=tk.E)

    def on_double_click_sysreg(self, event):
        item_id = self.sysreg_tree.identify_row(event.y)
        column = self.sysreg_tree.identify_column(event.x)

        if column == '#2' and item_id:
            x, y, width, height = self.sysreg_tree.bbox(item_id, column)
            value = self.sysreg_tree.item(item_id, "values")[1]

            entry = tk.Entry(self.sysreg_tree)
            entry.place(x=x, y=y, width=width, height=height)
            entry.insert(0, value)
            entry.focus()

            self.editing_entry = entry

            def save_edit(event=None):
                new_val = entry.get().strip()
                try:
                    val_int = int(new_val, 16)
                    if not (0 <= val_int <= 0xFFFF):
                        raise ValueError
                    self.sysreg_tree.set(item_id, column="value", value=f"{val_int:04X}")

                    addr_str = self.sysreg_tree.item(item_id, "values")[0]
                    addr = int(addr_str, 16)
                    self.modified_sysregs.add(addr)
                except ValueError:
                    messagebox.showerror("Ошибка", "Введите корректное 16-битное HEX значение")
                finally:
                    entry.destroy()
                    self.editing_entry = None

            entry.bind("<Return>", save_edit)
            entry.bind("<FocusOut>", save_edit)

            def cancel_edit(event=None):
                entry.destroy()
                self.editing_entry = None

            entry.bind("<Escape>", cancel_edit)

    def apply_sysreg_changes(self):
        if not self.modified_sysregs:
            messagebox.showinfo("Нет изменений", "Нет изменённых регистров для применения.")
            return

        for item in self.sysreg_tree.get_children():
            addr_str, val_str = self.sysreg_tree.item(item, "values")
            addr = int(addr_str, 16)

            if addr not in self.modified_sysregs:
                continue

            val = int(val_str, 16)
            try:
                self.spi_handler.write_system_register(addr, val)
                self.log_message(f"✓ Системный регистр 0x{addr:02X} обновлён: 0x{val:04X}")
            except Exception as e:
                self.log_message(f"✗ Ошибка записи 0x{addr:02X}: {e}")

        self.modified_sysregs.clear()
        messagebox.showinfo("Готово", "Изменения применены.")

def main():
    root = tk.Tk()
    app = SPIApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()