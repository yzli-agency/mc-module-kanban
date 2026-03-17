-- yzli/kanban — Initial Migration

-- Kanban cards
CREATE TABLE IF NOT EXISTS kanban_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    project_slug TEXT,
    client_slug TEXT,
    column_name TEXT DEFAULT 'Backlog',
    priority TEXT DEFAULT 'normal',
    assignee TEXT,
    due_date TEXT,
    cells TEXT,
    linked_agents TEXT,
    linked_docs TEXT,
    initial_prompt TEXT,
    synthesis TEXT,
    steps TEXT,
    workflow TEXT,
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kanban_client ON kanban_cards(client_slug);
CREATE INDEX IF NOT EXISTS idx_kanban_project ON kanban_cards(project_slug);
CREATE INDEX IF NOT EXISTS idx_kanban_column ON kanban_cards(column_name);

-- Kanban history
CREATE TABLE IF NOT EXISTS kanban_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER REFERENCES kanban_cards(id),
    from_column TEXT,
    to_column TEXT,
    moved_by TEXT,
    moved_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kanban_history_card ON kanban_history(card_id);
