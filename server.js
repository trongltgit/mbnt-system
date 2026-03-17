const express = require('express');
const cors = require('cors');
const { Pool } = require('pg');
const { createServer } = require('http');
const { Server } = require('socket.io');
require('dotenv').config();

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    }
});

app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// Kết nối PostgreSQL
const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false }
});

// Store socket connections by user ID
const userSockets = new Map();

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
        
        -- Bảng quotes realtime
        CREATE TABLE IF NOT EXISTS quotes (
            id SERIAL PRIMARY KEY,
            quote_id VARCHAR(100) UNIQUE NOT NULL,
            pnv_id VARCHAR(50) NOT NULL,
            pnv_name VARCHAR(200),
            pql_id VARCHAR(50),
            cif VARCHAR(20),
            customer_name VARCHAR(500),
            direction VARCHAR(50),
            buy_curr VARCHAR(10),
            sell_curr VARCHAR(10),
            amount DECIMAL(20,2),
            rate DECIMAL(20,4),
            duration INTEGER,
            purpose_code VARCHAR(10),
            purpose_name VARCHAR(500),
            effective_date DATE,
            status VARCHAR(20) DEFAULT 'pending',
            interrupted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expiry_time TIMESTAMP,
            quoted_at TIMESTAMP,
            accepted_at TIMESTAMP,
            rejected_at TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_quotes_pnv ON quotes(pnv_id);
        CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
        
        -- Bảng chat messages
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            from_id VARCHAR(50) NOT NULL,
            from_name VARCHAR(200),
            from_role VARCHAR(20),
            to_id VARCHAR(50),
            to_role VARCHAR(20),
            message TEXT,
            is_broadcast BOOLEAN DEFAULT FALSE,
            read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Bảng transactions
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            trans_id VARCHAR(100) UNIQUE NOT NULL,
            pnv_id VARCHAR(50) NOT NULL,
            pnv_name VARCHAR(200),
            date DATE,
            effective_date DATE,
            cif VARCHAR(20),
            customer_name VARCHAR(500),
            direction VARCHAR(10),
            buy_curr VARCHAR(10),
            sell_curr VARCHAR(10),
            amount DECIMAL(20,2),
            rate DECIMAL(20,4),
            balanced_rate DECIMAL(20,4),
            equivalent DECIMAL(20,2),
            type VARCHAR(10),
            status VARCHAR(50),
            purpose_code VARCHAR(10),
            purpose_name VARCHAR(500),
            profit DECIMAL(20,2),
            edited_by VARCHAR(50),
            edit_time TIMESTAMP,
            edit_note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    `);
    console.log('✅ Database ready');
}
initDB();

// Socket.IO connection handling
io.on('connection', (socket) => {
    console.log('Client connected:', socket.id);
    
    // User đăng ký với user ID
    socket.on('register', (userId) => {
        userSockets.set(userId, socket.id);
        socket.userId = userId;
        console.log(`User ${userId} registered with socket ${socket.id}`);
    });
    
    // PNV gửi yêu cầu hỏi giá
    socket.on('ask_price', async (data) => {
        try {
            const quoteId = 'Q' + Date.now();
            
            await pool.query(`
                INSERT INTO quotes 
                (quote_id, pnv_id, pnv_name, cif, customer_name, direction, 
                 buy_curr, sell_curr, amount, purpose_code, purpose_name, 
                 effective_date, status, expiry_time)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending', NOW() + INTERVAL '10 minutes')
            `, [
                quoteId, data.pnvId, data.pnvName, data.cif, data.customerName,
                data.direction, data.buyCurr, data.sellCurr, data.amount,
                data.purposeCode, data.purposeName, data.effectiveDate
            ]);
            
            // Gửi đến tất cả PQL
            io.emit('new_quote_request', {
                quoteId,
                ...data
            });
            
            socket.emit('quote_submitted', { quoteId, success: true });
        } catch (err) {
            console.error('Error saving quote:', err);
            socket.emit('quote_error', { error: err.message });
        }
    });
    
    // PQL chào giá
    socket.on('submit_quote', async (data) => {
        try {
            const expiryTime = new Date(Date.now() + data.duration * 60000);
            
            await pool.query(`
                UPDATE quotes 
                SET rate = $1, duration = $2, pql_id = $3, 
                    status = 'quoted', quoted_at = NOW(), expiry_time = $4
                WHERE quote_id = $5
            `, [data.rate, data.duration, data.pqlId, expiryTime, data.quoteId]);
            
            // Gửi realtime đến PNV cụ thể
            const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [data.quoteId]);
            const pnvId = quote.rows[0]?.pnv_id;
            
            const quoteData = {
                quoteId: data.quoteId,
                rate: data.rate,
                duration: data.duration,
                expiryTime: expiryTime.toISOString(),
                pqlId: data.pqlId
            };
            
            // Gửi qua socket nếu online
            const pnvSocketId = userSockets.get(pnvId);
            if (pnvSocketId) {
                io.to(pnvSocketId).emit('price_quote', quoteData);
            }
            
            // Gửi qua broadcast để polling client cũng nhận được
            io.emit('quote_update', { quoteId: data.quoteId, pnvId, ...quoteData });
            
        } catch (err) {
            console.error('Error submitting quote:', err);
            socket.emit('quote_error', { error: err.message });
        }
    });
    
    // PNV chấp nhận/từ chối giá
    socket.on('respond_quote', async (data) => {
        try {
            const { quoteId, accepted, pnvId } = data;
            
            const status = accepted ? 'accepted' : 'rejected';
            const timeField = accepted ? 'accepted_at' : 'rejected_at';
            
            await pool.query(`
                UPDATE quotes 
                SET status = $1, ${timeField} = NOW()
                WHERE quote_id = $2
            `, [status, quoteId]);
            
            if (accepted) {
                // Tạo transaction
                const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [quoteId]);
                const q = quote.rows[0];
                
                const transId = 'T' + Date.now();
                const balancedRate = q.rate * (q.direction === 'VCB MUA' ? 1.002 : 0.998);
                const profit = q.direction === 'VCB MUA' 
                    ? q.amount * (balancedRate - q.rate)
                    : q.amount * (q.rate - balancedRate);
                
                await pool.query(`
                    INSERT INTO transactions 
                    (trans_id, pnv_id, pnv_name, date, effective_date, cif, customer_name,
                     direction, buy_curr, sell_curr, amount, rate, balanced_rate, equivalent,
                     type, status, purpose_code, purpose_name, profit)
                    VALUES ($1, $2, $3, NOW(), $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 'Thành công', $15, $16, $17)
                `, [
                    transId, q.pnv_id, q.pnv_name, q.effective_date, q.cif, q.customer_name,
                    q.direction === 'VCB MUA' ? 'MUA' : 'BÁN', q.buy_curr, q.sell_curr,
                    q.amount, q.rate, balancedRate, q.amount * q.rate,
                    'GN', q.purpose_code, q.purpose_name, profit
                ]);
            }
            
            // Thông báo cho PQL
            io.emit('quote_responded', { quoteId, accepted, pnvId });
            
        } catch (err) {
            console.error('Error responding to quote:', err);
        }
    });
    
    // PQL Interrupt
    socket.on('interrupt_quote', async (data) => {
        try {
            const { quoteId, all } = data;
            
            if (all) {
                await pool.query(`
                    UPDATE quotes 
                    SET interrupted = TRUE, status = 'interrupted'
                    WHERE status = 'quoted' AND interrupted = FALSE AND expiry_time > NOW()
                `);
                io.emit('all_interrupted', { by: socket.userId });
            } else if (quoteId) {
                await pool.query(`
                    UPDATE quotes 
                    SET interrupted = TRUE, status = 'interrupted'
                    WHERE quote_id = $1
                `, [quoteId]);
                
                const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [quoteId]);
                const pnvId = quote.rows[0]?.pnv_id;
                
                const pnvSocketId = userSockets.get(pnvId);
                if (pnvSocketId) {
                    io.to(pnvSocketId).emit('quote_interrupted', { quoteId });
                }
            }
        } catch (err) {
            console.error('Error interrupting:', err);
        }
    });
    
    // Chat messages
    socket.on('chat_message', async (data) => {
        try {
            await pool.query(`
                INSERT INTO chat_messages 
                (from_id, from_name, from_role, to_id, to_role, message, is_broadcast)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            `, [
                data.fromId, data.fromName, data.fromRole,
                data.toId, data.toRole, data.message,
                !data.toId // broadcast if no specific target
            ]);
            
            if (data.toId) {
                // Private message
                const targetSocket = userSockets.get(data.toId);
                if (targetSocket) {
                    io.to(targetSocket).emit('new_message', data);
                }
            } else {
                // Broadcast
                io.emit('new_message', data);
            }
        } catch (err) {
            console.error('Error saving chat:', err);
        }
    });
    
    socket.on('disconnect', () => {
        console.log('Client disconnected:', socket.id);
        if (socket.userId) {
            userSockets.delete(socket.userId);
        }
    });
});

// REST API endpoints
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

// API: Get pending quotes for PQL
app.get('/api/quotes/pending', async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT * FROM quotes 
            WHERE status = 'pending' AND interrupted = FALSE
            ORDER BY created_at DESC
        `);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// API: Get my quotes (PNV)
app.get('/api/quotes/my/:pnvId', async (req, res) => {
    try {
        const result = await pool.query(`
            SELECT * FROM quotes 
            WHERE pnv_id = $1 
            ORDER BY created_at DESC
            LIMIT 50
        `, [req.params.pnvId]);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// API: Get transactions
app.get('/api/transactions', async (req, res) => {
    try {
        const { pnvId, from, to } = req.query;
        let query = 'SELECT * FROM transactions WHERE 1=1';
        const params = [];
        
        if (pnvId) {
            params.push(pnvId);
            query += ` AND pnv_id = $${params.length}`;
        }
        if (from) {
            params.push(from);
            query += ` AND date >= $${params.length}`;
        }
        if (to) {
            params.push(to);
            query += ` AND date <= $${params.length}`;
        }
        
        query += ' ORDER BY created_at DESC LIMIT 1000';
        
        const result = await pool.query(query, params);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Health check
app.get('/health', (req, res) => res.json({ status: 'OK', sockets: userSockets.size }));

const PORT = process.env.PORT || 3000;
httpServer.listen(PORT, () => console.log(`🚀 Server running on port ${PORT}`));
