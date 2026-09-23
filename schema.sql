-- TSC TOOL schema
-- MariaDB / MySQL

CREATE DATABASE IF NOT EXISTS tsc_tool
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE tsc_tool;

-- Generic key-value settings shared across users.
-- Currently used for the exclude-devices list.
CREATE TABLE IF NOT EXISTS settings (
    `name` VARCHAR(100) PRIMARY KEY,
    `value` TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Seed default exclude devices (idempotent)
INSERT INTO settings (`name`, `value`) VALUES
    ('exclude_devices', 'MGZ_NG_PORT_02,MGZ_NG_PORT_03,MGZ_NG_PORT_04,CST_NG_PORT_02')
ON DUPLICATE KEY UPDATE `name` = `name`;
