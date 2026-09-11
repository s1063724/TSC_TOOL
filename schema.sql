-- Dispatch Generator schema
-- MariaDB / MySQL

CREATE DATABASE IF NOT EXISTS dispatch_generator
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE dispatch_generator;

CREATE TABLE IF NOT EXISTS presets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    config JSON NOT NULL,
    updated_by VARCHAR(50),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
