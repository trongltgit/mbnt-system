-- File này để tham khảo, server.js đã tự tạo bảng
-- Không cần chạy thủ công

CREATE TABLE IF NOT EXISTS mbnt_data (
    id SERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL UNIQUE,
    data_json JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
