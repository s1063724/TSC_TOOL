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

-- ============================================================
-- Vehicle-log analysis: TSC/AGVL Spec versions + per-message
-- byte layout. Field defs stored as JSON so future spec versions
-- can define new field shapes without schema migration.
-- ============================================================
CREATE TABLE IF NOT EXISTS spec_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `version` VARCHAR(20) NOT NULL UNIQUE,
    label VARCHAR(200) NOT NULL,
    source VARCHAR(200),
    is_default TINYINT(1) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS spec_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    spec_id INT NOT NULL,
    msg_id VARCHAR(10) NOT NULL,
    description VARCHAR(300),
    direction VARCHAR(20),
    structure VARCHAR(100),
    fields JSON,
    raw_text TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_spec_msg (spec_id, msg_id),
    FOREIGN KEY (spec_id) REFERENCES spec_versions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
