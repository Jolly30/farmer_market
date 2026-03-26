CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'user', -- user / admin
    seller_status TEXT DEFAULT 'none', -- none / pending / approved / rejected
    active_mode TEXT DEFAULT 'buyer', -- buyer / seller
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
, is_admin INTEGER NOT NULL DEFAULT 0, full_name TEXT, phone TEXT, address TEXT, bio TEXT, profile_image TEXT, bank_name TEXT, bank_account TEXT, payapp_name TEXT, payapp_phone TEXT, delivery_available INTEGER DEFAULT 1, delivery_eta TEXT, farm_name TEXT, business_hours TEXT, facebook_link TEXT, website_link TEXT, location_city TEXT, contact_preference TEXT, tagline TEXT, whatsapp TEXT, location TEXT, pending_email TEXT, email_otp_code TEXT, email_otp_expires_at DATETIME, reset_otp_code TEXT, reset_otp_expires_at DATETIME, email_verified INTEGER NOT NULL DEFAULT 0);
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
, image_path TEXT);
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    image_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, min_order_qty INTEGER DEFAULT 1, payment_methods TEXT, payment_details TEXT, delivery_option TEXT, delivery_eta TEXT, payment_options TEXT, delivery_options TEXT, delivery_methods TEXT,
    
    FOREIGN KEY (seller_id) REFERENCES users(id),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);
CREATE TABLE requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    status TEXT DEFAULT 'pending', -- pending / accepted / rejected / completed
    buyer_completed INTEGER DEFAULT 0, -- 0 = false, 1 = true
    seller_completed INTEGER DEFAULT 0, -- 0 = false, 1 = true
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP, seller_note TEXT, seller_comment TEXT, payment_method TEXT, buyer_note TEXT, expected_delivery TEXT, delivery_method TEXT, buyer_seen INTEGER DEFAULT 1, seller_seen INTEGER DEFAULT 1, snap_title TEXT, snap_price TEXT, snap_unit TEXT, snap_image_path TEXT, snap_min_order_qty INTEGER, snap_delivery_eta TEXT, buyer_last_seen_msg_id INTEGER DEFAULT 0, seller_last_seen_msg_id INTEGER DEFAULT 0,

    FOREIGN KEY (buyer_id) REFERENCES users(id),
    FOREIGN KEY (seller_id) REFERENCES users(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, image_path TEXT,

    FOREIGN KEY (request_id) REFERENCES requests(id),
    FOREIGN KEY (sender_id) REFERENCES users(id)
);
CREATE TABLE seller_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    farm_name TEXT NOT NULL,
    note TEXT,
    document_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
