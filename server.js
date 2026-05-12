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
    cors: { origin: "*", methods: ["GET", "POST"] },
    transports: ['websocket', 'polling']
});

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.static('public'));

const pool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: process.env.NODE_ENV === 'production' ? { rejectUnauthorized: false } : false
});

const connectedUsers = new Map();

async function initDB() {
    try {
        await pool.query(`
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR(50) PRIMARY KEY, name VARCHAR(200) NOT NULL,
                dept VARCHAR(100), role VARCHAR(20) NOT NULL,
                password VARCHAR(100) NOT NULL DEFAULT 'Vcb@1234',
                manager_id VARCHAR(50), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cif_data (cif VARCHAR(20) PRIMARY KEY, name VARCHAR(500) NOT NULL);
            CREATE TABLE IF NOT EXISTS purpose_data (
                code VARCHAR(10) PRIMARY KEY, name TEXT NOT NULL, type VARCHAR(10) DEFAULT 'buy'
            );
            CREATE TABLE IF NOT EXISTS assignment_data (cif VARCHAR(20) PRIMARY KEY, pnv_id VARCHAR(50) NOT NULL);
            CREATE TABLE IF NOT EXISTS quotes (
                id SERIAL PRIMARY KEY, quote_id VARCHAR(100) UNIQUE NOT NULL,
                pnv_id VARCHAR(50) NOT NULL, pnv_name VARCHAR(200), pql_id VARCHAR(50),
                cif VARCHAR(20), customer_name VARCHAR(500), direction VARCHAR(50),
                buy_curr VARCHAR(10), sell_curr VARCHAR(10), amount DECIMAL(20,2),
                rate DECIMAL(20,4), duration INTEGER, purpose_code VARCHAR(10),
                purpose_name VARCHAR(500), effective_date DATE,
                status VARCHAR(20) DEFAULT 'pending', interrupted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expiry_time TIMESTAMP,
                quoted_at TIMESTAMP, accepted_at TIMESTAMP, rejected_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY, trans_id VARCHAR(100) UNIQUE NOT NULL,
                pnv_id VARCHAR(50) NOT NULL, pnv_name VARCHAR(200),
                trans_date DATE DEFAULT CURRENT_DATE, effective_date DATE,
                cif VARCHAR(20), customer_name VARCHAR(500), direction VARCHAR(10),
                buy_curr VARCHAR(10), sell_curr VARCHAR(10), amount DECIMAL(20,2),
                rate DECIMAL(20,4), balanced_rate DECIMAL(20,4), equivalent DECIMAL(20,2),
                trans_type VARCHAR(10) DEFAULT 'GN', status VARCHAR(50) DEFAULT 'Thành công',
                purpose_code VARCHAR(10), purpose_name VARCHAR(500), profit DECIMAL(20,2),
                edited_by VARCHAR(50), edit_time TIMESTAMP, edit_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id SERIAL PRIMARY KEY, msg_id VARCHAR(100) UNIQUE NOT NULL,
                from_id VARCHAR(50) NOT NULL, from_name VARCHAR(200), from_role VARCHAR(20),
                to_id VARCHAR(50), to_role VARCHAR(20), message TEXT NOT NULL,
                is_broadcast BOOLEAN DEFAULT FALSE, is_read BOOLEAN DEFAULT FALSE,
                quote_id VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS plan_sales (
                id SERIAL PRIMARY KEY, dept VARCHAR(100) NOT NULL, year INTEGER DEFAULT 2026,
                quarter INTEGER, month INTEGER, plan_amount DECIMAL(20,2) DEFAULT 0,
                actual_amount DECIMAL(20,2) DEFAULT 0, actual_daily DECIMAL(20,2) DEFAULT 0,
                UNIQUE(dept, year, month)
            );
            CREATE TABLE IF NOT EXISTS plan_profit (
                id SERIAL PRIMARY KEY, dept VARCHAR(100) NOT NULL, year INTEGER DEFAULT 2026,
                quarter INTEGER, month INTEGER, plan_amount DECIMAL(20,2) DEFAULT 0,
                actual_amount DECIMAL(20,2) DEFAULT 0, actual_daily DECIMAL(20,2) DEFAULT 0,
                margin_avg DECIMAL(5,2) DEFAULT 0, UNIQUE(dept, year, month)
            );
            CREATE TABLE IF NOT EXISTS forward_transactions (
                id SERIAL PRIMARY KEY, cif VARCHAR(20) NOT NULL, customer_name VARCHAR(500),
                direction VARCHAR(10) NOT NULL, currency VARCHAR(10) NOT NULL,
                amount DECIMAL(20,2) NOT NULL, rate DECIMAL(20,4) NOT NULL,
                trade_date DATE NOT NULL, maturity_date DATE NOT NULL,
                tenor_days INTEGER, daily_allocation DECIMAL(20,2) DEFAULT 0,
                cumulative_allocation DECIMAL(20,2) DEFAULT 0, status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS fx_limits (
                id SERIAL PRIMARY KEY, year INTEGER DEFAULT 2026,
                total_limit DECIMAL(20,2) DEFAULT 84380382, used_limit DECIMAL(20,2) DEFAULT 0,
                remaining_limit DECIMAL(20,2) DEFAULT 84380382,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS fx_limit_usage (
                id SERIAL PRIMARY KEY, trade_date DATE NOT NULL, cif VARCHAR(20) NOT NULL,
                customer_name VARCHAR(500), currency VARCHAR(10), amount_vnd DECIMAL(20,2),
                rate_tsc DECIMAL(20,4), rate_customer DECIMAL(20,4), spread DECIMAL(20,4),
                budget_used DECIMAL(20,2), dept VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_quotes_pnv ON quotes(pnv_id);
            CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
            CREATE INDEX IF NOT EXISTS idx_transactions_pnv ON transactions(pnv_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(trans_date);
            CREATE INDEX IF NOT EXISTS idx_chat_to ON chat_messages(to_id);
            CREATE INDEX IF NOT EXISTS idx_chat_from ON chat_messages(from_id);
            CREATE INDEX IF NOT EXISTS idx_forward_cif ON forward_transactions(cif);
            CREATE INDEX IF NOT EXISTS idx_forward_date ON forward_transactions(trade_date);
        `);

        const adminCheck = await pool.query('SELECT * FROM users WHERE id = $1', ['admin']);
        if (adminCheck.rows.length === 0) {
            await pool.query(`INSERT INTO users (id, name, dept, role, password, manager_id)
                VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (id) DO NOTHING`,
                ['admin','Administrator','IT','admin','Vcb@1234',null]);
            await pool.query(`INSERT INTO users (id, name, dept, role, password, manager_id) VALUES
                ($1,$2,$3,$4,$5,$6),($7,$8,$9,$10,$11,$12),($13,$14,$15,$16,$17,$18)
                ON CONFLICT (id) DO NOTHING`,
                ['K001','Nguyễn Văn A','KHDN1 (K1)','PNV','Vcb@1234','BGD001',
                 'KT001','Hoàng Văn E','PQL - Kế toán','PQL','Vcb@1234',null,
                 'BGD001','Giám đốc A','Ban Giám đốc','BGD','Vcb@1234',null]);

            await pool.query(`INSERT INTO cif_data (cif, name) VALUES
                ('0000123456','CÔNG TY TNHH ABC'),('0000987654','TẬP ĐOÀN XYZ'),
                ('0001122334','NGÂN HÀNG DEF'),('0002233445','CÔNG TY CP GHI'),
                ('0003344556','TẬP ĐOÀN JKL') ON CONFLICT (cif) DO NOTHING`);

            await pool.query(`INSERT INTO purpose_data (code, name, type) VALUES
                ('1','Thanh toán nhập khẩu hàng hóa','buy'),('2','Thanh toán nhập khẩu dịch vụ','buy'),
                ('3','Chuyển tiền một chiều','buy'),('4','Chuyển thu nhập đầu tư ra nước ngoài','buy'),
                ('5','Chuyển lợi nhuận','buy'),('6','Đầu tư trực tiếp ra nước ngoài','buy'),
                ('7','Chuyển thu nhập đầu tư gián tiếp','buy'),('8','Thanh toán lãi và nợ gốc vay nước ngoài','buy'),
                ('9','Thanh toán lãi và nợ gốc vay trong nước','buy'),('10','Thanh toán thẻ quốc tế','buy'),
                ('11','Bán ngoại tệ cho Kho bạc','buy'),('12','Mục đích khác','buy'),
                ('1','Nguồn thu từ xuất khẩu hàng hóa','sell'),('2','Nguồn thu từ xuất khẩu dịch vụ','sell'),
                ('3','Chuyển tiền một chiều','sell'),('4','Giải ngân vốn đầu tư trực tiếp nước ngoài (FDI)','sell'),
                ('5','Giải ngân vốn vay nước ngoài','sell'),('6','Giải ngân vốn vay trong nước bằng ngoại tệ','sell'),
                ('7','Nguồn khác','sell') ON CONFLICT (code) DO NOTHING`);

            const depts = ['KHDN1','KHDN2','KHDN3','FDI','KHBL1','KHBL2','KHBL3',
                'DVKHTC1','DVKHTC2','PGD TĐT','PGD ML','PGD ĐK','PGD CH','PGD VVK','PGD LTT'];
            for (const dept of depts) {
                await pool.query(`INSERT INTO plan_sales (dept, year, month, plan_amount)
                    VALUES ($1,2026,5,$2) ON CONFLICT (dept, year, month) DO NOTHING`, [dept, Math.floor(Math.random()*500+100)]);
                await pool.query(`INSERT INTO plan_profit (dept, year, month, plan_amount, margin_avg)
                    VALUES ($1,2026,5,$2,$3) ON CONFLICT (dept, year, month) DO NOTHING`,
                    [dept, Math.floor(Math.random()*50+10), Math.floor(Math.random()*100+20)]);
            }
            await pool.query(`INSERT INTO fx_limits (year, total_limit, used_limit, remaining_limit)
                VALUES (2026,84380382,51310523,33069859) ON CONFLICT DO NOTHING`);
        }
        console.log('✅ Database initialized');
    } catch (err) {
        console.error('❌ Database init error:', err);
    }
}
initDB();

// SOCKET.IO
io.on('connection', (socket) => {
    socket.on('register', async (userId) => {
        socket.userId = userId;
        connectedUsers.set(userId, socket.id);
        try {
            const unread = await pool.query(`SELECT * FROM chat_messages WHERE to_id = $1 AND is_read = FALSE ORDER BY created_at ASC`, [userId]);
            if (unread.rows.length > 0) {
                socket.emit('unread_messages', unread.rows);
                await pool.query(`UPDATE chat_messages SET is_read = TRUE WHERE to_id = $1 AND is_read = FALSE`, [userId]);
            }
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('ask_price', async (data) => {
        try {
            const quoteId = 'Q' + Date.now();
            await pool.query(`INSERT INTO quotes (quote_id, pnv_id, pnv_name, cif, customer_name, direction, buy_curr, sell_curr, amount, purpose_code, purpose_name, effective_date, status, expiry_time)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'pending',NOW()+INTERVAL'10 minutes')`,
                [quoteId, data.pnvId, data.pnvName, data.cif, data.customerName, data.direction, data.buyCurr, data.sellCurr, data.amount, data.purposeCode, data.purposeName, data.effectiveDate]);
            const pqlUsers = await pool.query("SELECT id FROM users WHERE role = 'PQL'");
            pqlUsers.rows.forEach(pql => {
                const pqlSocket = connectedUsers.get(pql.id);
                if (pqlSocket) io.to(pqlSocket).emit('new_quote_request', { quoteId, ...data, timestamp: new Date().toISOString() });
            });
            socket.emit('quote_submitted', { quoteId, success: true });
        } catch (err) { socket.emit('quote_error', { error: err.message }); }
    });

    socket.on('submit_quote', async (data) => {
        try {
            const expiryTime = new Date(Date.now() + (data.duration || 2) * 60000);
            await pool.query(`UPDATE quotes SET rate=$1, duration=$2, pql_id=$3, status='quoted', quoted_at=NOW(), expiry_time=$4 WHERE quote_id=$5`,
                [data.rate, data.duration, data.pqlId, expiryTime, data.quoteId]);
            const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [data.quoteId]);
            const q = quote.rows[0];
            const quoteData = { quoteId: data.quoteId, rate: data.rate, duration: data.duration, expiryTime: expiryTime.toISOString(), pqlId: data.pqlId, pqlName: data.pqlName || data.pqlId, cif: q.cif, customerName: q.customer_name, direction: q.direction, buyCurr: q.buy_curr, sellCurr: q.sell_curr, amount: q.amount };
            const pnvSocketId = connectedUsers.get(q.pnv_id);
            if (pnvSocketId) io.to(pnvSocketId).emit('price_quote', quoteData);
            io.emit('quote_updated', { quoteId: data.quoteId, pnvId: q.pnv_id, status: 'quoted' });
        } catch (err) { socket.emit('quote_error', { error: err.message }); }
    });

    socket.on('respond_quote', async (data) => {
        try {
            const { quoteId, accepted, pnvId } = data;
            const status = accepted ? 'accepted' : 'rejected';
            const timeField = accepted ? 'accepted_at' : 'rejected_at';
            await pool.query(`UPDATE quotes SET status = $1, ${timeField} = NOW() WHERE quote_id = $2`, [status, quoteId]);
            if (accepted) {
                const quote = await pool.query('SELECT * FROM quotes WHERE quote_id = $1', [quoteId]);
                const q = quote.rows[0];
                const transId = 'T' + Date.now();
                const direction = q.direction === 'VCB MUA' ? 'MUA' : 'BÁN';
                const rate = parseFloat(q.rate);
                const balancedRate = direction === 'MUA' ? rate * 1.002 : rate * 0.998;
                const amount = parseFloat(q.amount);
                const equivalent = amount * rate;
                const profit = direction === 'MUA' ? amount * (balancedRate - rate) : amount * (rate - balancedRate);
                await pool.query(`INSERT INTO transactions (trans_id, pnv_id, pnv_name, trans_date, effective_date, cif, customer_name, direction, buy_curr, sell_curr, amount, rate, balanced_rate, equivalent, trans_type, status, purpose_code, purpose_name, profit)
                    VALUES ($1,$2,$3,CURRENT_DATE,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)`,
                    [transId, q.pnv_id, q.pnv_name, q.effective_date, q.cif, q.customer_name, direction, q.buy_curr, q.sell_curr, amount, rate, balancedRate, equivalent, 'GN', 'Thành công', q.purpose_code, q.purpose_name, profit]);
                await updatePlanActuals(q.pnv_id, amount, profit);
            }
            const quote = await pool.query('SELECT pql_id FROM quotes WHERE quote_id = $1', [quoteId]);
            const pqlId = quote.rows[0]?.pql_id;
            if (pqlId) {
                const pqlSocket = connectedUsers.get(pqlId);
                if (pqlSocket) io.to(pqlSocket).emit('quote_responded', { quoteId, accepted, pnvId });
            }
            socket.emit('response_recorded', { quoteId, accepted });
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('interrupt_quote', async (data) => {
        try {
            if (data.all) {
                await pool.query(`UPDATE quotes SET interrupted = TRUE, status = 'interrupted' WHERE status = 'quoted' AND interrupted = FALSE AND expiry_time > NOW()`);
                const activeQuotes = await pool.query(`SELECT pnv_id FROM quotes WHERE status = 'interrupted' AND interrupted = TRUE`);
                activeQuotes.rows.forEach(row => {
                    const pnvSocket = connectedUsers.get(row.pnv_id);
                    if (pnvSocket) io.to(pnvSocket).emit('quote_interrupted', { all: true });
                });
                io.emit('all_interrupted', { by: socket.userId });
            } else if (data.quoteId) {
                await pool.query(`UPDATE quotes SET interrupted = TRUE, status = 'interrupted' WHERE quote_id = $1`, [data.quoteId]);
                const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [data.quoteId]);
                const pnvId = quote.rows[0]?.pnv_id;
                const pnvSocket = connectedUsers.get(pnvId);
                if (pnvSocket) io.to(pnvSocket).emit('quote_interrupted', { quoteId: data.quoteId });
            }
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('withdraw_quote', async (data) => {
        try {
            await pool.query(`UPDATE quotes SET status = 'withdrawn' WHERE quote_id = $1`, [data.quoteId]);
            const quote = await pool.query('SELECT pnv_id FROM quotes WHERE quote_id = $1', [data.quoteId]);
            const pnvId = quote.rows[0]?.pnv_id;
            const pnvSocket = connectedUsers.get(pnvId);
            if (pnvSocket) io.to(pnvSocket).emit('quote_withdrawn', { quoteId: data.quoteId });
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('transfer_quote', async (data) => {
        try {
            await pool.query(`UPDATE quotes SET pql_id = $1 WHERE quote_id = $2`, [data.toPql, data.quoteId]);
            io.emit('quote_transferred', data);
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('chat_message', async (data) => {
        try {
            const msgId = 'M' + Date.now();
            await pool.query(`INSERT INTO chat_messages (msg_id, from_id, from_name, from_role, to_id, to_role, message, is_broadcast, quote_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
                [msgId, data.fromId, data.fromName, data.fromRole, data.toId || null, data.toRole || null, data.message, !data.toId, data.quoteId || null]);
            const msgData = { msgId, fromId: data.fromId, fromName: data.fromName, fromRole: data.fromRole, message: data.message, timestamp: new Date().toISOString(), quoteId: data.quoteId };
            if (data.toId) {
                const targetSocket = connectedUsers.get(data.toId);
                if (targetSocket) io.to(targetSocket).emit('new_message', msgData);
                socket.emit('message_sent', msgData);
            } else {
                if (data.toRole) {
                    const targets = await pool.query('SELECT id FROM users WHERE role = $1', [data.toRole]);
                    targets.rows.forEach(t => {
                        if (t.id !== data.fromId) {
                            const targetSocket = connectedUsers.get(t.id);
                            if (targetSocket) io.to(targetSocket).emit('new_message', msgData);
                        }
                    });
                }
                socket.emit('message_sent', msgData);
            }
        } catch (err) { console.error('Error:', err); }
    });

    socket.on('disconnect', () => { if (socket.userId) connectedUsers.delete(socket.userId); });
});

async function updatePlanActuals(pnvId, amount, profit) {
    try {
        const user = await pool.query('SELECT dept FROM users WHERE id = $1', [pnvId]);
        if (user.rows.length === 0) return;
        const dept = user.rows[0].dept;
        const now = new Date();
        await pool.query(`INSERT INTO plan_sales (dept, year, month, actual_amount, actual_daily)
            VALUES ($1,$2,$3,$4,$4) ON CONFLICT (dept, year, month) DO UPDATE SET
            actual_amount = plan_sales.actual_amount + $4, actual_daily = plan_sales.actual_daily + $4`, [dept, now.getFullYear(), now.getMonth() + 1, amount / 1000000]);
        await pool.query(`INSERT INTO plan_profit (dept, year, month, actual_amount, actual_daily)
            VALUES ($1,$2,$3,$4,$4) ON CONFLICT (dept, year, month) DO UPDATE SET
            actual_amount = plan_profit.actual_amount + $4, actual_daily = plan_profit.actual_daily + $4`, [dept, now.getFullYear(), now.getMonth() + 1, profit / 1000000000]);
    } catch (err) { console.error('Error:', err); }
}

// REST API
app.get('/health', (req, res) => res.json({ status: 'OK', connectedUsers: connectedUsers.size, timestamp: new Date().toISOString() }));

app.post('/api/login', async (req, res) => {
    try {
        const { userId, password } = req.body;
        const result = await pool.query('SELECT * FROM users WHERE id = $1 AND password = $2', [userId, password]);
        if (result.rows.length === 0) return res.status(401).json({ error: 'Invalid credentials' });
        const user = result.rows[0];
        res.json({ id: user.id, name: user.name, dept: user.dept, role: user.role, managerId: user.manager_id });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/users', async (req, res) => {
    try { const result = await pool.query('SELECT id, name, dept, role, manager_id FROM users ORDER BY id'); res.json(result.rows); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/users', async (req, res) => {
    try {
        const { id, name, dept, role, password, managerId } = req.body;
        await pool.query(`INSERT INTO users (id, name, dept, role, password, manager_id) VALUES ($1,$2,$3,$4,$5,$6)`, [id, name, dept, role, password || 'Vcb@1234', managerId]);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.put('/api/users/:id', async (req, res) => {
    try {
        const { name, dept, role, managerId } = req.body;
        const updates = []; const values = []; let idx = 1;
        if (name) { updates.push(`name = $${idx++}`); values.push(name); }
        if (dept) { updates.push(`dept = $${idx++}`); values.push(dept); }
        if (role) { updates.push(`role = $${idx++}`); values.push(role); }
        if (managerId !== undefined) { updates.push(`manager_id = $${idx++}`); values.push(managerId); }
        if (req.body.password) { updates.push(`password = $${idx++}`); values.push(req.body.password); }
        values.push(req.params.id);
        await pool.query(`UPDATE users SET ${updates.join(', ')} WHERE id = $${idx}`, values);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.delete('/api/users/:id', async (req, res) => {
    try { await pool.query('DELETE FROM users WHERE id = $1', [req.params.id]); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/change-password', async (req, res) => {
    try {
        const { userId, currentPassword, newPassword } = req.body;
        const check = await pool.query('SELECT * FROM users WHERE id = $1 AND password = $2', [userId, currentPassword]);
        if (check.rows.length === 0) return res.status(401).json({ error: 'Current password incorrect' });
        await pool.query('UPDATE users SET password = $1 WHERE id = $2', [newPassword, userId]);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/cif', async (req, res) => {
    try { const result = await pool.query('SELECT * FROM cif_data ORDER BY cif'); const cifObj = {}; result.rows.forEach(r => cifObj[r.cif] = r.name); res.json(cifObj); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/cif/bulk', async (req, res) => {
    try {
        const { data } = req.body; const client = await pool.connect();
        try { await client.query('BEGIN'); for (const item of data) { await client.query(`INSERT INTO cif_data (cif, name) VALUES ($1,$2) ON CONFLICT (cif) DO UPDATE SET name = $2`, [item.cif, item.name]); } await client.query('COMMIT'); res.json({ success: true, count: data.length }); }
        catch (err) { await client.query('ROLLBACK'); throw err; } finally { client.release(); }
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.delete('/api/cif/:cif', async (req, res) => {
    try { await pool.query('DELETE FROM cif_data WHERE cif = $1', [req.params.cif]); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/purpose', async (req, res) => {
    try { const type = req.query.type || 'buy'; const result = await pool.query('SELECT * FROM purpose_data WHERE type = $1 ORDER BY code', [type]); const purposeObj = {}; result.rows.forEach(r => purposeObj[r.code] = r.name); res.json(purposeObj); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/purpose/bulk', async (req, res) => {
    try {
        const { data } = req.body; const client = await pool.connect();
        try { await client.query('BEGIN'); for (const item of data) { await client.query(`INSERT INTO purpose_data (code, name, type) VALUES ($1,$2,$3) ON CONFLICT (code) DO UPDATE SET name = $2, type = $3`, [item.code, item.name, item.type || 'buy']); } await client.query('COMMIT'); res.json({ success: true, count: data.length }); }
        catch (err) { await client.query('ROLLBACK'); throw err; } finally { client.release(); }
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/assignment', async (req, res) => {
    try { const result = await pool.query('SELECT * FROM assignment_data ORDER BY cif'); const assignObj = {}; result.rows.forEach(r => assignObj[r.cif] = r.pnv_id); res.json(assignObj); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/assignment/bulk', async (req, res) => {
    try {
        const { data } = req.body; const client = await pool.connect();
        try { await client.query('BEGIN'); for (const item of data) { await client.query(`INSERT INTO assignment_data (cif, pnv_id) VALUES ($1,$2) ON CONFLICT (cif) DO UPDATE SET pnv_id = $2`, [item.cif, item.pnvId]); } await client.query('COMMIT'); res.json({ success: true, count: data.length }); }
        catch (err) { await client.query('ROLLBACK'); throw err; } finally { client.release(); }
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.delete('/api/assignment/:cif', async (req, res) => {
    try { await pool.query('DELETE FROM assignment_data WHERE cif = $1', [req.params.cif]); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/quotes/pending', async (req, res) => {
    try { const result = await pool.query(`SELECT * FROM quotes WHERE status = 'pending' AND interrupted = FALSE ORDER BY created_at DESC`); res.json(result.rows); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/quotes/my/:pnvId', async (req, res) => {
    try { const result = await pool.query(`SELECT * FROM quotes WHERE pnv_id = $1 ORDER BY created_at DESC LIMIT 50`, [req.params.pnvId]); res.json(result.rows); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/transactions', async (req, res) => {
    try {
        const { pnvId, from, to, status, transId } = req.query;
        if (transId) { const result = await pool.query('SELECT * FROM transactions WHERE trans_id = $1', [transId]); return res.json(result.rows[0] || null); }
        let query = 'SELECT * FROM transactions WHERE 1=1'; const params = []; let paramCount = 0;
        if (pnvId) { params.push(pnvId); query += ` AND pnv_id = $${++paramCount}`; }
        if (from) { params.push(from); query += ` AND trans_date >= $${++paramCount}`; }
        if (to) { params.push(to); query += ` AND trans_date <= $${++paramCount}`; }
        if (status) { params.push(status); query += ` AND status = $${++paramCount}`; }
        query += ' ORDER BY created_at DESC LIMIT 1000';
        const result = await pool.query(query, params); res.json(result.rows);
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.put('/api/transactions/:transId', async (req, res) => {
    try {
        const { cif, customerName, effectiveDate, buyCurr, sellCurr, amount, rate, balancedRate, transType, editedBy, editNote } = req.body;
        await pool.query(`UPDATE transactions SET cif=$1, customer_name=$2, effective_date=$3, buy_curr=$4, sell_curr=$5, amount=$6, rate=$7, balanced_rate=$8, trans_type=$9, edited_by=$10, edit_time=NOW(), edit_note=$11, status='Đã sửa' WHERE trans_id=$12`,
            [cif, customerName, effectiveDate, buyCurr, sellCurr, amount, rate, balancedRate, transType, editedBy, editNote, req.params.transId]);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.put('/api/transactions/:transId/balanced-rate', async (req, res) => {
    try { const { balancedRate, editedBy } = req.body; await pool.query(`UPDATE transactions SET balanced_rate=$1, edited_by=$2, edit_time=NOW() WHERE trans_id=$3`, [balancedRate, editedBy, req.params.transId]); res.json({ success: true }); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

app.get('/api/chat/history', async (req, res) => {
    try { const { userId, limit = 100 } = req.query; const result = await pool.query(`SELECT * FROM chat_messages WHERE from_id = $1 OR to_id = $1 OR is_broadcast = TRUE ORDER BY created_at DESC LIMIT $2`, [userId, limit]); res.json(result.rows.reverse()); }
    catch (err) { res.status(500).json({ error: err.message }); }
});

// BÁO CÁO API - 6 SHEETS

// Sheet 01.GD - Giao dịch MUA_BÁN
app.get('/api/reports/transactions', async (req, res) => {
    try {
        const { date, type } = req.query;
        let query = `SELECT t.trans_id as "CF_NO", u.dept as "Phòng QL", t.trans_type as "Loại GD", t.cif as "CIF", t.customer_name as "Tên", CASE WHEN t.direction = 'MUA' THEN t.buy_curr ELSE t.sell_curr END as "Loại tiền", t.amount as "Số tiền", t.rate as "TG mua", t.balanced_rate as "TG bán", COALESCE(t.balanced_rate - t.rate, 0) as "C/lệch", t.profit as "Lãi", t.purpose_code as "Mục đích/Nguồn", t.purpose_name as "Tên Mục đích/Nguồn", t.direction FROM transactions t LEFT JOIN users u ON t.pnv_id = u.id WHERE 1=1`;
        const params = [];
        if (date) { params.push(date); query += ` AND t.trans_date = $${params.length}`; }
        if (type && type !== 'all') { params.push(type === 'buy' ? 'MUA' : 'BÁN'); query += ` AND t.direction = $${params.length}`; }
        query += ' ORDER BY u.dept, t.created_at DESC';
        const result = await pool.query(query, params);
        const grouped = {};
        result.rows.forEach(row => { const dept = row['Phòng QL'] || 'Không xác định'; if (!grouped[dept]) grouped[dept] = []; grouped[dept].push(row); });
        const deptTotals = {};
        for (const [dept, rows] of Object.entries(grouped)) { deptTotals[dept] = rows.reduce((sum, r) => sum + (parseFloat(r['Lãi']) || 0), 0); }
        res.json({ date: date || new Date().toISOString().split('T')[0], sections: [{ name: 'KHÁCH HÀNG MUA NGOẠI TỆ', data: result.rows.filter(r => r.direction === 'MUA'), totals: deptTotals }, { name: 'KHÁCH HÀNG BÁN NGOẠI TỆ', data: result.rows.filter(r => r.direction === 'BÁN'), totals: deptTotals }], grandTotal: result.rows.reduce((sum, r) => sum + (parseFloat(r['Lãi']) || 0), 0) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// Sheet 02.KH - Kế hoạch Doanh số
app.get('/api/reports/plan-sales', async (req, res) => {
    try {
        const { year = 2026, month } = req.query;
        const query = month ? `SELECT * FROM plan_sales WHERE year = $1 AND month = $2 ORDER BY dept` : `SELECT dept, year, SUM(plan_amount) as plan_amount, SUM(actual_amount) as actual_amount, SUM(actual_daily) as actual_daily FROM plan_sales WHERE year = $1 GROUP BY dept, year ORDER BY dept`;
        const params = month ? [year, month] : [year];
        const result = await pool.query(query, params);
        const data = result.rows.map(row => ({ dept: row.dept, daily: parseFloat(row.actual_daily) || 0, monthly: parseFloat(row.actual_amount) || 0, cumulative: parseFloat(row.actual_amount) || 0, plan: parseFloat(row.plan_amount) || 0, percent: row.plan_amount > 0 ? ((row.actual_amount / row.plan_amount) * 100).toFixed(2) : 0, vsSamePeriod: 0, vsLastMonth: 0, vsYesterday: 0 }));
        const typeResult = await pool.query(`SELECT trans_type, SUM(amount) as total FROM transactions WHERE EXTRACT(YEAR FROM trans_date) = $1 ${month ? 'AND EXTRACT(MONTH FROM trans_date) = $2' : ''} GROUP BY trans_type`, params);
        const byType = {}; typeResult.rows.forEach(r => { byType[r.trans_type] = parseFloat(r.total) || 0; });
        res.json({ year, month, data, byType: { giaoNgay: byType['GN'] || 0, kyHan: byType['KH'] || 0, hoanDoi: byType['HD'] || 0 }, totalPlan: data.reduce((s, r) => s + r.plan, 0), totalActual: data.reduce((s, r) => s + r.monthly, 0), totalPercent: data.length > 0 ? (data.reduce((s, r) => s + r.monthly, 0) / data.reduce((s, r) => s + r.plan, 0) * 100).toFixed(2) : 0 });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// Sheet 03.LN - Kế hoạch Lợi nhuận (Thực tế)
app.get('/api/reports/plan-profit', async (req, res) => {
    try {
        const { year = 2026, month } = req.query;
        const query = month ? `SELECT * FROM plan_profit WHERE year = $1 AND month = $2 ORDER BY dept` : `SELECT dept, year, SUM(plan_amount) as plan_amount, SUM(actual_amount) as actual_amount, SUM(actual_daily) as actual_daily, AVG(margin_avg) as margin_avg FROM plan_profit WHERE year = $1 GROUP BY dept, year ORDER BY dept`;
        const params = month ? [year, month] : [year];
        const result = await pool.query(query, params);
        const data = result.rows.map(row => ({ dept: row.dept, daily: parseFloat(row.actual_daily) || 0, monthly: parseFloat(row.actual_amount) || 0, cumulative: parseFloat(row.actual_amount) || 0, plan: parseFloat(row.plan_amount) || 0, percent: row.plan_amount > 0 ? ((row.actual_amount / row.plan_amount) * 100).toFixed(2) : 0, margin: parseFloat(row.margin_avg) || 0 }));
        res.json({ year, month, note: 'KHÔNG BAO GỒM PHÂN BỔ LÃI LỖ VÀ ĐÁNH GIÁ LẠI', unit: 'Tỷ VND', data, totalPlan: data.reduce((s, r) => s + r.plan, 0), totalActual: data.reduce((s, r) => s + r.monthly, 0), totalPercent: data.length > 0 ? (data.reduce((s, r) => s + r.monthly, 0) / data.reduce((s, r) => s + r.plan, 0) * 100).toFixed(2) : 0 });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// Sheet 04.TT - Kế hoạch Lợi nhuận (Tạm tính)
app.get('/api/reports/plan-profit-temp', async (req, res) => {
    try {
        const { year = 2026, month } = req.query;
        const query = month ? `SELECT * FROM plan_profit WHERE year = $1 AND month = $2 ORDER BY dept` : `SELECT dept, year, SUM(plan_amount) as plan_amount, SUM(actual_amount) as actual_amount, SUM(actual_daily) as actual_daily, AVG(margin_avg) as margin_avg FROM plan_profit WHERE year = $1 GROUP BY dept, year ORDER BY dept`;
        const params = month ? [year, month] : [year];
        const result = await pool.query(query, params);
        const data = result.rows.map(row => ({ dept: row.dept, daily: parseFloat(row.actual_daily) || 0, monthly: parseFloat(row.actual_amount) || 0, cumulative: parseFloat(row.actual_amount) || 0, plan: parseFloat(row.plan_amount) || 0, percent: row.plan_amount > 0 ? ((row.actual_amount / row.plan_amount) * 100).toFixed(2) : 0, margin: parseFloat(row.margin_avg) || 0 }));
        const forwardAlloc = await pool.query(`SELECT SUM(daily_allocation) as total FROM forward_transactions WHERE status = 'active' AND EXTRACT(YEAR FROM trade_date) = $1 ${month ? 'AND EXTRACT(MONTH FROM trade_date) = $2' : ''}`, params);
        const revaluation = await pool.query(`SELECT SUM(cumulative_allocation) as total FROM forward_transactions WHERE status = 'active' AND EXTRACT(YEAR FROM trade_date) = $1 ${month ? 'AND EXTRACT(MONTH FROM trade_date) = $2' : ''}`, params);
        res.json({ year, month, note: 'THEO NGUYÊN TẮC HẠCH TOÁN CÂN ĐỐI', unit: 'Tỷ VND', data, extraRows: { forwardAllocation: parseFloat(forwardAlloc.rows[0]?.total) || 0, revaluation: parseFloat(revaluation.rows[0]?.total) || 0, sharedTSC: 0 }, totalPlan: data.reduce((s, r) => s + r.plan, 0), totalActual: data.reduce((s, r) => s + r.monthly, 0), totalPercent: data.length > 0 ? (data.reduce((s, r) => s + r.monthly, 0) / data.reduce((s, r) => s + r.plan, 0) * 100).toFixed(2) : 0 });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// Sheet 05.BAN - Chi tiết Giao dịch Kỳ hạn
app.get('/api/reports/forward', async (req, res) => {
    try {
        const { date, status = 'active' } = req.query;
        let query = `SELECT id as "STT", cif as "CIF", customer_name as "Tên KH", direction as "Sell/Buy", currency as "NT", amount as "Số tiền", rate as "Tỷ giá giao dịch", trade_date as "Ngày giao dịch", maturity_date as "Ngày đến hạn", tenor_days as "Kỳ hạn", daily_allocation as "Giá trị phân bổ lãi lỗ ngày" FROM forward_transactions WHERE status = $1`;
        const params = [status];
        if (date) { params.push(date); query += ` AND trade_date = $${params.length}`; }
        query += ' ORDER BY trade_date DESC';
        const result = await pool.query(query, params);
        const totalAllocation = result.rows.reduce((s, r) => s + (parseFloat(r['Giá trị phân bổ lãi lỗ ngày']) || 0), 0);
        res.json({ date: date || new Date().toISOString().split('T')[0], sections: [{ name: 'Giao dịch kỳ hạn phát sinh', data: result.rows.filter(r => new Date(r['Ngày giao dịch']) >= new Date()) }, { name: 'Giao dịch kỳ hạn đến hạn', data: result.rows.filter(r => new Date(r['Ngày đến hạn']) <= new Date()) }], totalAllocation, topDeals: result.rows.sort((a, b) => (parseFloat(b['Giá trị phân bổ lãi lỗ ngày']) || 0) - (parseFloat(a['Giá trị phân bổ lãi lỗ ngày']) || 0)).slice(0, 10) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/reports/forward', async (req, res) => {
    try {
        const { cif, customerName, direction, currency, amount, rate, tradeDate, maturityDate, dailyAllocation } = req.body;
        const tenorDays = Math.ceil((new Date(maturityDate) - new Date(tradeDate)) / (1000 * 60 * 60 * 24));
        await pool.query(`INSERT INTO forward_transactions (cif, customer_name, direction, currency, amount, rate, trade_date, maturity_date, tenor_days, daily_allocation, status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'active')`, [cif, customerName, direction, currency, amount, rate, tradeDate, maturityDate, tenorDays, dailyAllocation]);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

// Sheet 06.MUA - Hạn mức Điều hòa Tỷ giá
app.get('/api/reports/fx-limit', async (req, res) => {
    try {
        const { year = 2026 } = req.query;
        const limitResult = await pool.query('SELECT * FROM fx_limits WHERE year = $1', [year]);
        const limit = limitResult.rows[0] || { total_limit: 84380382, used_limit: 0, remaining_limit: 84380382 };
        const usageResult = await pool.query(`SELECT trade_date as "Ngày giao dịch", cif as "CIF", customer_name as "Tên khách hàng", currency as "Loại tiền", amount_vnd as "Số tiền (VNĐ)", rate_tsc as "Tỷ giá thực hiện với TSC", rate_customer as "Tỷ giá thực hiện với KH", spread as "Điểm bù", budget_used as "Ngân sách sử dụng", dept as "Phòng QL" FROM fx_limit_usage WHERE EXTRACT(YEAR FROM trade_date) = $1 ORDER BY trade_date DESC`, [year]);
        const byCustomer = {};
        usageResult.rows.forEach(row => { const cif = row.CIF; if (!byCustomer[cif]) byCustomer[cif] = { cif, name: row['Tên khách hàng'], totalBudget: 0, transactions: [] }; byCustomer[cif].totalBudget += parseFloat(row['Ngân sách sử dụng']) || 0; byCustomer[cif].transactions.push(row); });
        res.json({ year, limit: { total: parseFloat(limit.total_limit) || 84380382, used: parseFloat(limit.used_limit) || 0, remaining: parseFloat(limit.remaining_limit) || 84380382 }, transactions: usageResult.rows, byCustomer: Object.values(byCustomer), totalBudgetUsed: usageResult.rows.reduce((s, r) => s + (parseFloat(r['Ngân sách sử dụng']) || 0), 0) });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

app.post('/api/reports/fx-limit', async (req, res) => {
    try {
        const { tradeDate, cif, customerName, currency, amountVnd, rateTsc, rateCustomer, spread, budgetUsed, dept } = req.body;
        await pool.query(`INSERT INTO fx_limit_usage (trade_date, cif, customer_name, currency, amount_vnd, rate_tsc, rate_customer, spread, budget_used, dept) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`, [tradeDate, cif, customerName, currency, amountVnd, rateTsc, rateCustomer, spread, budgetUsed, dept]);
        await pool.query(`UPDATE fx_limits SET used_limit = used_limit + $1, remaining_limit = remaining_limit - $1, updated_at = NOW() WHERE year = $2`, [budgetUsed, new Date().getFullYear()]);
        res.json({ success: true });
    } catch (err) { res.status(500).json({ error: err.message }); }
});

const PORT = process.env.PORT || 3000;
httpServer.listen(PORT, () => { console.log(`🚀 Server running on port ${PORT}`); });
