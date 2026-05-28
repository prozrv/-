CREATE TABLE IF NOT EXISTS commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    code INTEGER NOT NULL,
    tx_len INTEGER NOT NULL,
    rx_len INTEGER NOT NULL,
    description TEXT
);

-- Добавляем базовые команды (пример из кода)
INSERT OR IGNORE INTO commands (name, code, tx_len, rx_len, description) VALUES
('write_register', 0x13, 3, 0, 'Write register (code, address, value)'),
('read_register',  0x14, 2, 1, 'Read register (code, address -> 1 byte)');

-- Можешь добавить свои команды:
-- ('read_status',   0x15, 1, 2, 'Read 2-byte status register'),
-- ('reset_device',  0x01, 1, 0, 'Hardware reset');

-- Проверка содержимого
SELECT * FROM commands;