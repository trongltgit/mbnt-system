const express = require('express');
const cors = require('cors');
const { Pool } = require('pg');
require('dotenv').config();

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// Kết nối PostgreSQL
const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false }
});

// Tạo bảng nếu chưa có
async function initDB() {
    await pool.query(`
        CREATE TABLE IF NOT EXISTS mbnt_data (
            id SERIAL PRIMARY KEY,
            data_type VARCHAR(50) NOT NULL,
            data_json JSONB NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE UNIQUE INDEX IF NOT EXISTS idx_data_type ON mbnt_data(data_type);
    `);
    console.log('✅ Database ready');
}
initDB();

// API: Lấy data
app.get('/api/data/:type', async (req, res) => {
    try {
        const result = await pool.query(
            'SELECT data_json FROM mbnt_data WHERE data_type = $1',
            [req.params.type]
        );
        res.json(result.rows[0]?.data_json || {});
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// API: Lưu data
app.post('/api/data/:type', async (req, res) => {
    try {
        const { data } = req.body;
        await pool.query(`
            INSERT INTO mbnt_data (data_type, data_json) 
            VALUES ($1, $2)
            ON CONFLICT (data_type) 
            DO UPDATE SET data_json = $2, updated_at = CURRENT_TIMESTAMP
        `, [req.params.type, JSON.stringify(data)]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Health check
app.get('/health', (req, res) => res.json({ status: 'OK' }));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🚀 Server running on port ${PORT}`));