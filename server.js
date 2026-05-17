const express = require('express');
const cors = require('cors');
const { Pool } = require('pg');
const { createServer } = require('http');
const { Server } = require('socket.io');
const path = require('path');
require('dotenv').config();

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
    cors: {
        origin: "*",
        methods: ["GET", "POST"]
    },
    transports: ['websocket', 'polling']
});

app.use(cors());
app.use(express.json());
app.use(express.static('public'));

// PostgreSQL connection
const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false }
});

// Track connected users: { userId: socketId }
const connectedUsers = new Map();

// Initialize database tables
async function initDB() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                dept VARCHAR(100),
                role VARCHAR(20) NOT NULL,
                password VARCHAR(100) NOT NULL,
                manager_id VARCHAR(50),
                managed_by_bgd VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cif_data (
                cif VARCHAR(20) PRIMARY KEY,
                name VARCHAR(500) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS purpose_data (
                code VARCHAR(10) PRIMARY KEY,
                name TEXT NOT NULL
            );

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

            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                trans_id VARCHAR(100) UNIQUE NOT NULL,
                pnv_id VARCHAR(50) NOT NULL,
                pnv_name VARCHAR(200),
                pnv_dept VARCHAR(200),
                trans_date DATE,
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
                trans_type VARCHAR(10),
                status VARCHAR(50),
                purpose_code VARCHAR(10),
                purpose_name VARCHAR(500),
                profit DECIMAL(20,2),
                edited_by VARCHAR(50),
                edit_time TIMESTAMP,
                edit_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS assignment_data (
                cif VARCHAR(20) PRIMARY KEY,
                pnv_id VARCHAR(50) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY,
                msg_id VARCHAR(100) UNIQUE NOT NULL,
                from_id VARCHAR(50) NOT NULL,
                from_name VARCHAR(200),
                from_role VARCHAR(20),
                to_id VARCHAR(50),
                to_role VARCHAR(20),
                message TEXT NOT NULL,
                is_broadcast BOOLEAN DEFAULT FALSE,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_quotes_pnv ON quotes(pnv_id);
            CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
            CREATE INDEX IF NOT EXISTS idx_transactions_pnv ON transactions(pnv_id);
            CREATE INDEX IF NOT EXISTS idx_chat_to ON chat_messages(to_id);
            CREATE INDEX IF NOT EXISTS idx_chat_from ON chat_messages(from_id);
        `);

        // Insert default admin if not exists
        const adminCheck = await pool.query('SELECT * FROM users WHERE id = $1', ['admin']);
        if (adminCheck.rows.length === 0) {
            await pool.query(`
                INSERT INTO users (id, name, dept, role, password, manager_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO NOTHING
            `, ['admin', 'Administrator', 'IT', 'admin', 'Vcb@1234', null]);
            
            await pool.query(`
                INSERT INTO users (id, name, dept, role, password, manager_id)
                VALUES 
                ($1, $2, $3, $4, $5, $6),
                ($7, $8, $9, $10, $11, $12),
                ($13, $14, $15, $16, $17, $18)
                ON CONFLICT (id) DO NOTHING
            `, [
                'K001', 'Nguyễn Văn A', 'KHDN1 (K1)', 'PNV', 'Vcb@1234', 'BGD001',
                'KT001', 'Hoàng Văn E', 'PQL - Kế toán', 'PQL', 'Vcb@1234', null,
                'BGD001', 'Giám đốc A', 'Ban Giám đốc', 'BGD', 'Vcb@1234', null
            ]);

            // Insert default CIF data
            await pool.query(`
                INSERT INTO cif_data (cif, name) VALUES
                ('0000123456', 'CÔNG TY TNHH ABC'),
                ('0000987654', 'TẬP ĐOÀN XYZ'),
                ('0001122334', 'NGÂN HÀNG DEF'),
                ('0002233445', 'CÔNG TY CP GHI'),
                ('0003344556', 'TẬP ĐOÀN JKL')
                ON CONFLICT (cif) DO NOTHING
            `);

            // Insert default purpose data
            await pool.query(`
                INSERT INTO purpose_data (code, name) VALUES
                ('1', 'Thanh toán nhập khẩu hàng hóa'),
                ('2', 'Thanh toán nhập khẩu dịch vụ'),
                ('3', 'Chuyển tiền một chiều'),
                ('4', 'Chuyển thu nhập đầu tư ra nước ngoài'),
                ('5', 'Chuyển lợi nhuận'),
                ('6', 'Đầu tư trực tiếp ra nước ngoài'),
                ('7', 'Chuyển thu nhập đầu tư gián tiếp'),
                ('8', 'Thanh toán lãi và nợ gốc vay nước ngoài'),
                ('9', 'Thanh toán lãi và nợ gốc vay trong nước'),
                ('10', 'Thanh toán thẻ quốc tế'),
                ('11', 'Bán ngoại tệ cho Kho bạc'),
                ('12', 'Mục đích khác')
                ON CONFLICT (code) DO NOTHING
            `);
        }

        console.log('✅ Database initialized');
    } catch (err) {
        console.error('❌ Database init error:', err);
    }
}

initDB();

// Socket.IO handling
io.on('connection', (socket) => {
    console.log('🔌 Client connected:', socket.id);

    // User register with their ID
    socket.on('register', async (userId) => {
        socket.userId = userId;
        connectedUsers.set(userId, socket.id);
        console.log(`👤 User ${userId} registered with socket ${socket.id}`);
        
        // Send unread messages to user
        try {
            const unread = await pool.query(`
                SELECT * FROM chat_messages 
                WHERE to_id = $1 AND is_read = FALSE 
                ORDER BY created_at ASC
            `, [userId]);
            
            if (unread.rows.length > 0) {
                socket.emit('unread_messages', unread.rows);
                
                // Mark as read
                await pool.query(`
                    UPDATE chat_messages SET is_read = TRUE 
                    WHERE to_id = $1 AND is_read = FALSE
                `, [userId]);
            }
        } catch (err) {
            console.error('Error fetching unread messages:', err);
        }
    });

    // PNV asks for price
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

            // Notify all PQL users
            const pqlUsers = await pool.query("SELECT id FROM users WHERE role = 'PQL'");
            pqlUsers.rows.forEach(pql => {
                const pqlSocket = connectedUsers.get(pql.id);
                if (pqlSocket) {
                    io.to(pqlSocket).emit('new_quote_request', {
                        quoteId,
                        ...data,
                        timestamp: new Date().toISOString()
                    });
                }
            });

            socket.emit('quote_submitted', { quoteId, success: true });
            console.log(`📤 Quote ${quoteId} submitted by ${data.pnvId}`);
        } catch (err) {
            console.error('Error in ask_price:', err);
            socket.emit('quote_error', { error: err.message });
        }
    });

    // PQL withdraws price quote
    socket.on('withdraw_quote', async (data) => {
        try {
            const { quoteId, pqlId } = data;
            
            await pool.query(`
                UPDATE quotes 
                SET status = 'withdrawn', interrupted = TRUE
                WHERE quote_id = $1
            `, [quoteId]);

            // Notify PNV
            const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [quoteId]);
            const pnvId = quote.rows[0]?.pnv_id;
            const pnvSocket = connectedUsers.get(pnvId);
            if (pnvSocket) {
                io.to(pnvSocket).emit('quote_withdrawn', { quoteId, pqlId });
            }

            console.log(`🔄 Quote ${quoteId} withdrawn by ${pqlId}`);
        } catch (err) {
            console.error('Error in withdraw_quote:', err);
        }
    });

    // PQL transfers quote to another PQL user
    socket.on('transfer_quote', async (data) => {
        try {
            const { quoteId, fromPqlId, toPqlId } = data;
            
            await pool.query(`
                UPDATE quotes 
                SET pql_id = $1, status = 'quoted'
                WHERE quote_id = $2
            `, [toPqlId, quoteId]);

            // Notify the new PQL user
            const toPqlSocket = connectedUsers.get(toPqlId);
            if (toPqlSocket) {
                const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [quoteId]);
                const q = quote.rows[0];
                io.to(toPqlSocket).emit('quote_transferred_to_me', {
                    quoteId,
                    fromPqlId,
                    quote: q
                });
            }

            console.log(`📨 Quote ${quoteId} transferred from ${fromPqlId} to ${toPqlId}`);
        } catch (err) {
            console.error('Error in transfer_quote:', err);
        }
    });

    // PQL submits price quote
    socket.on('submit_quote', async (data) => {
        try {
            const expiryTime = new Date(Date.now() + data.duration * 60000);
            
            await pool.query(`
                UPDATE quotes 
                SET rate = $1, duration = $2, pql_id = $3, 
                    status = 'quoted', quoted_at = NOW(), expiry_time = $4
                WHERE quote_id = $5
            `, [data.rate, data.duration, data.pqlId, expiryTime, data.quoteId]);

            // Get PNV info
            const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [data.quoteId]);
            const q = quote.rows[0];
            
            const quoteData = {
                quoteId: data.quoteId,
                rate: data.rate,
                duration: data.duration,
                expiryTime: expiryTime.toISOString(),
                pqlId: data.pqlId,
                cif: q.cif,
                customerName: q.customer_name,
                direction: q.direction,
                buyCurr: q.buy_curr,
                sellCurr: q.sell_curr,
                amount: q.amount
            };

            // Send to specific PNV
            const pnvSocketId = connectedUsers.get(q.pnv_id);
            if (pnvSocketId) {
                io.to(pnvSocketId).emit('price_quote', quoteData);
                console.log(`💰 Quote sent to PNV ${q.pnv_id}`);
            }

            // Also broadcast for any polling clients
            io.emit('quote_updated', { quoteId: data.quoteId, pnvId: q.pnv_id, status: 'quoted' });
        } catch (err) {
            console.error('Error in submit_quote:', err);
            socket.emit('quote_error', { error: err.message });
        }
    });

    // PNV responds to quote (accept/reject)
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
                // Create transaction
                const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [quoteId]);
                const q = quote.rows[0];
                
                // Get PNV dept
                const userRes = await pool.query('SELECT dept FROM users WHERE id = $1', [q.pnv_id]);
                const pnvDept = userRes.rows[0]?.dept || '';

                const transId = 'T' + Date.now();
                const direction = q.direction === 'VCB MUA' ? 'MUA' : 'BÁN';
                const balancedRate = parseFloat(q.rate) * (direction === 'MUA' ? 1.002 : 0.998);
                const equivalent = parseFloat(q.amount) * parseFloat(q.rate);
                const profit = direction === 'MUA' 
                    ? parseFloat(q.amount) * (balancedRate - parseFloat(q.rate))
                    : parseFloat(q.amount) * (parseFloat(q.rate) - balancedRate);

                await pool.query(`
                    INSERT INTO transactions 
                    (trans_id, pnv_id, pnv_name, pnv_dept, trans_date, effective_date, cif, customer_name,
                     direction, buy_curr, sell_curr, amount, rate, balanced_rate, equivalent,
                     trans_type, status, purpose_code, purpose_name, profit)
                    VALUES ($1, $2, $3, $4, CURRENT_DATE, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                `, [
                    transId, q.pnv_id, q.pnv_name, pnvDept, q.effective_date, q.cif, q.customer_name,
                    direction, q.buy_curr, q.sell_curr, q.amount, q.rate, balancedRate, 
                    equivalent, 'GN', 'Thành công', q.purpose_code, q.purpose_name, profit
                ]);

                console.log(`✅ Transaction ${transId} created`);
            }

            // Notify PQL
            const quote = await pool.query('SELECT pql_id FROM quotes WHERE quote_id = $1', [quoteId]);
            const pqlId = quote.rows[0]?.pql_id;
            if (pqlId) {
                const pqlSocket = connectedUsers.get(pqlId);
                if (pqlSocket) {
                    io.to(pqlSocket).emit('quote_responded', { quoteId, accepted, pnvId });
                }
            }

            socket.emit('response_recorded', { quoteId, accepted });
        } catch (err) {
            console.error('Error in respond_quote:', err);
        }
    });

    // Interrupt quote(s)
    socket.on('interrupt_quote', async (data) => {
        try {
            if (data.all) {
                await pool.query(`
                    UPDATE quotes 
                    SET interrupted = TRUE, status = 'interrupted'
                    WHERE status = 'quoted' AND interrupted = FALSE AND expiry_time > NOW()
                `);
                
                // Notify all PNV with active quotes
                const activeQuotes = await pool.query(`
                    SELECT pnv_id FROM quotes 
                    WHERE status = 'interrupted' AND interrupted = TRUE
                `);
                
                activeQuotes.rows.forEach(row => {
                    const pnvSocket = connectedUsers.get(row.pnv_id);
                    if (pnvSocket) {
                        io.to(pnvSocket).emit('quote_interrupted', { all: true });
                    }
                });
                
                io.emit('all_interrupted', { by: socket.userId });
                console.log('⛔ All quotes interrupted');
            } else if (data.quoteId) {
                await pool.query(`
                    UPDATE quotes 
                    SET interrupted = TRUE, status = 'interrupted'
                    WHERE quote_id = $1
                `, [data.quoteId]);
                
                const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [data.quoteId]);
                const pnvId = quote.rows[0]?.pnv_id;
                
                const pnvSocket = connectedUsers.get(pnvId);
                if (pnvSocket) {
                    io.to(pnvSocket).emit('quote_interrupted', { quoteId: data.quoteId });
                }
            }
        } catch (err) {
            console.error('Error in interrupt:', err);
        }
    });

    // Chat message
    socket.on('chat_message', async (data) => {
        try {
            const msgId = 'M' + Date.now();
            
            await pool.query(`
                INSERT INTO chat_messages 
                (msg_id, from_id, from_name, from_role, to_id, to_role, message, is_broadcast)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            `, [
                msgId, data.fromId, data.fromName, data.fromRole,
                data.toId || null, data.toRole || null, data.message,
                !data.toId
            ]);

            const msgData = {
                msgId,
                fromId: data.fromId,
                fromName: data.fromName,
                fromRole: data.fromRole,
                message: data.message,
                timestamp: new Date().toISOString()
            };

            if (data.toId) {
                // Private message
                const targetSocket = connectedUsers.get(data.toId);
                if (targetSocket) {
                    io.to(targetSocket).emit('new_message', msgData);
                }
                // Also send to sender for confirmation
                socket.emit('message_sent', msgData);
            } else {
                // Broadcast to all users of target role
                if (data.toRole) {
                    const targets = await pool.query('SELECT id FROM users WHERE role = $1', [data.toRole]);
                    targets.rows.forEach(t => {
                        if (t.id !== data.fromId) {
                            const targetSocket = connectedUsers.get(t.id);
                            if (targetSocket) {
                                io.to(targetSocket).emit('new_message', msgData);
                            }
                        }
                    });
                }
                socket.emit('message_sent', msgData);
            }
        } catch (err) {
            console.error('Error in chat:', err);
        }
    });

    socket.on('disconnect', () => {
        console.log('🔌 Client disconnected:', socket.id);
        if (socket.userId) {
            connectedUsers.delete(socket.userId);
        }
    });
});

// REST API Routes

// ========== MIGRATION 001 - THÊM TẠM, CHẠY XONG XÓA ==========
app.get('/run-migration-001', async (req, res) => {
    try {
        // Step 1: Add column
        await pool.query(`
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS managed_by_bgd VARCHAR(50)
        `);
        
        // Step 2: Add comment
        await pool.query(`
            COMMENT ON COLUMN users.managed_by_bgd 
            IS 'ID của BGD quản lý user này. Chỉ áp dụng cho PNV users.'
        `);
        
        // Step 3: Verify
        const result = await pool.query(`
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name = 'users' AND column_name = 'managed_by_bgd'
        `);
        
        res.json({
            success: true,
            message: 'Migration 001 completed - managed_by_bgd column added',
            column: result.rows[0] || null
        });
        
    } catch (err) {
        console.error('Migration error:', err);
        res.status(500).json({ 
            success: false, 
            error: err.message 
        });
    }
});
// ========== KẾT THÚC MIGRATION 001 ==========

// Login
app.post('/api/login', async (req, res) => {
    try {
        const { userId, password } = req.body;
        const result = await pool.query('SELECT * FROM users WHERE id = $1 AND password = $2', [userId, password]);
        
        if (result.rows.length === 0) {
            return res.status(401).json({ error: 'Invalid credentials' });
        }
        
        const user = result.rows[0];
        res.json({
            id: user.id,
            name: user.name,
            dept: user.dept,
            role: user.role,
            managerId: user.manager_id
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get all users (admin)
app.get('/api/users', async (req, res) => {
    try {
        const result = await pool.query('SELECT id, name, dept, role, manager_id, managed_by_bgd FROM users ORDER BY id');
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Create user (admin)
app.post('/api/users', async (req, res) => {
    try {
        const { id, name, dept, role, password, managerId, managedByBgd } = req.body;
        await pool.query(`
            INSERT INTO users (id, name, dept, role, password, manager_id, managed_by_bgd)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        `, [id, name, dept, role, password || 'Vcb@1234', managerId, managedByBgd || null]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Update user
app.put('/api/users/:id', async (req, res) => {
    try {
        const { name, dept, role, managerId, managedByBgd } = req.body;
        await pool.query(`
            UPDATE users SET name = $1, dept = $2, role = $3, manager_id = $4, managed_by_bgd = $5
            WHERE id = $6
        `, [name, dept, role, managerId, managedByBgd || null, req.params.id]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Delete user
app.delete('/api/users/:id', async (req, res) => {
    try {
        await pool.query('DELETE FROM users WHERE id = $1', [req.params.id]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Change password
app.post('/api/change-password', async (req, res) => {
    try {
        const { userId, currentPassword, newPassword } = req.body;
        const check = await pool.query('SELECT * FROM users WHERE id = $1 AND password = $2', [userId, currentPassword]);
        
        if (check.rows.length === 0) {
            return res.status(401).json({ error: 'Current password incorrect' });
        }
        
        await pool.query('UPDATE users SET password = $1 WHERE id = $2', [newPassword, userId]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get CIF data
app.get('/api/cif', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM cif_data ORDER BY cif');
        const cifObj = {};
        result.rows.forEach(row => {
            cifObj[row.cif] = row.name;
        });
        res.json(cifObj);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Bulk insert CIF
app.post('/api/cif/bulk', async (req, res) => {
    try {
        const { data } = req.body; // [{cif, name}, ...]
        const client = await pool.connect();
        try {
            await client.query('BEGIN');
            for (const item of data) {
                await client.query(`
                    INSERT INTO cif_data (cif, name) VALUES ($1, $2)
                    ON CONFLICT (cif) DO UPDATE SET name = $2
                `, [item.cif, item.name]);
            }
            await client.query('COMMIT');
            res.json({ success: true, count: data.length });
        } catch (err) {
            await client.query('ROLLBACK');
            throw err;
        } finally {
            client.release();
        }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Delete CIF
app.delete('/api/cif/:cif', async (req, res) => {
    try {
        await pool.query('DELETE FROM cif_data WHERE cif = $1', [req.params.cif]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Bulk insert purpose
app.post('/api/purpose/bulk', async (req, res) => {
    try {
        const { data } = req.body;
        const client = await pool.connect();
        try {
            await client.query('BEGIN');
            for (const item of data) {
                await client.query(`
                    INSERT INTO purpose_data (code, name) VALUES ($1, $2)
                    ON CONFLICT (code) DO UPDATE SET name = $2
                `, [item.code, item.name]);
            }
            await client.query('COMMIT');
            res.json({ success: true, count: data.length });
        } catch (err) {
            await client.query('ROLLBACK');
            throw err;
        } finally {
            client.release();
        }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get pending quotes (PQL)
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

// Get my quotes (PNV)
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

// Get transactions with filters (join dept from users if pnv_dept empty)
app.get('/api/transactions', async (req, res) => {
    try {
        const { pnvId, from, to, status, direction, dept } = req.query;
        let query = `
            SELECT t.*, COALESCE(t.pnv_dept, u.dept, '') as phong_ql
            FROM transactions t
            LEFT JOIN users u ON t.pnv_id = u.id
            WHERE 1=1`;
        const params = [];
        let paramCount = 0;

        if (pnvId) { params.push(pnvId); query += ` AND t.pnv_id = $${++paramCount}`; }
        if (from)  { params.push(from);  query += ` AND t.trans_date >= $${++paramCount}`; }
        if (to)    { params.push(to);    query += ` AND t.trans_date <= $${++paramCount}`; }
        if (status){ params.push(status);query += ` AND t.status = $${++paramCount}`; }
        if (direction){ params.push(direction); query += ` AND t.direction = $${++paramCount}`; }
        if (dept)  { params.push(dept);  query += ` AND COALESCE(t.pnv_dept, u.dept, '') = $${++paramCount}`; }

        query += ' ORDER BY t.created_at DESC LIMIT 1000';
        const result = await pool.query(query, params);
        res.json(result.rows);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get single transaction
app.get('/api/transactions/:transId', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM transactions WHERE trans_id = $1', [req.params.transId]);
        if (result.rows.length === 0) return res.status(404).json({ error: 'Not found' });
        res.json(result.rows[0]);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Update balanced rate only
app.put('/api/transactions/:transId/balanced-rate', async (req, res) => {
    try {
        const { balancedRate, editedBy } = req.body;
        const t = await pool.query('SELECT * FROM transactions WHERE trans_id = $1', [req.params.transId]);
        if (t.rows.length === 0) return res.status(404).json({ error: 'Not found' });
        const row = t.rows[0];
        const newProfit = row.direction === 'MUA'
            ? parseFloat(row.amount) * (balancedRate - parseFloat(row.rate))
            : parseFloat(row.amount) * (parseFloat(row.rate) - balancedRate);
        await pool.query(`
            UPDATE transactions SET balanced_rate=$1, profit=$2, edited_by=$3, edit_time=NOW()
            WHERE trans_id=$4
        `, [balancedRate, newProfit, editedBy, req.params.transId]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Update transaction (full edit)
app.put('/api/transactions/:transId', async (req, res) => {
    try {
        const { cif, customerName, effectiveDate, buyCurr, sellCurr, amount, rate, balancedRate, transType, editedBy, editNote } = req.body;
        const equiv = parseFloat(amount) * parseFloat(rate);
        const t = await pool.query('SELECT direction FROM transactions WHERE trans_id=$1', [req.params.transId]);
        const dir = t.rows[0]?.direction;
        const br = balancedRate || rate;
        const profit = dir === 'MUA'
            ? parseFloat(amount) * (br - parseFloat(rate))
            : parseFloat(amount) * (parseFloat(rate) - br);
        await pool.query(`
            UPDATE transactions 
            SET cif=$1, customer_name=$2, effective_date=$3, buy_curr=$4, sell_curr=$5,
                amount=$6, rate=$7, balanced_rate=$8, equivalent=$9, trans_type=$10,
                edited_by=$11, edit_time=NOW(), edit_note=$12, profit=$13, status='Đã sửa'
            WHERE trans_id=$14
        `, [cif, customerName, effectiveDate, buyCurr, sellCurr, amount, rate, br, equiv, transType || 'GN', editedBy, editNote, profit, req.params.transId]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Assignment endpoints
app.get('/api/assignment', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM assignment_data ORDER BY cif');
        const obj = {};
        result.rows.forEach(r => { obj[r.cif] = r.pnv_id; });
        res.json(obj);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/assignment/bulk', async (req, res) => {
    try {
        const { data } = req.body;
        const client = await pool.connect();
        try {
            await client.query('BEGIN');
            for (const item of data) {
                await client.query(`
                    INSERT INTO assignment_data (cif, pnv_id) VALUES ($1, $2)
                    ON CONFLICT (cif) DO UPDATE SET pnv_id = $2
                `, [item.cif, item.pnvId]);
            }
            await client.query('COMMIT');
            res.json({ success: true, count: data.length });
        } catch (err) {
            await client.query('ROLLBACK');
            throw err;
        } finally { client.release(); }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.delete('/api/assignment/:cif', async (req, res) => {
    try {
        await pool.query('DELETE FROM assignment_data WHERE cif = $1', [req.params.cif]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get purpose data (supports ?type= filter for compatibility)
app.get('/api/purpose', async (req, res) => {
    try {
        const result = await pool.query('SELECT * FROM purpose_data ORDER BY code');
        const purposeObj = {};
        result.rows.forEach(row => { purposeObj[row.code] = row.name; });
        res.json(purposeObj);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Delete purpose
app.delete('/api/purpose/:code', async (req, res) => {
    try {
        await pool.query('DELETE FROM purpose_data WHERE code = $1', [req.params.code]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Get chat history
app.get('/api/chat/history', async (req, res) => {
    try {
        const { userId, limit = 100 } = req.query;
        const result = await pool.query(`
            SELECT * FROM chat_messages 
            WHERE from_id = $1 OR to_id = $1 OR is_broadcast = TRUE
            ORDER BY created_at DESC
            LIMIT $2
        `, [userId, limit]);
        res.json(result.rows.reverse());
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Health check
app.get('/health', (req, res) => {
    res.json({ 
        status: 'OK', 
        connectedUsers: connectedUsers.size,
        timestamp: new Date().toISOString()
    });
});

const PORT = process.env.PORT || 3000;
httpServer.listen(PORT, () => {
    console.log(`🚀 Server running on port ${PORT}`);
});
