CREATE TABLE events (
    event_id bigint GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    payload text NOT NULL,
    PRIMARY KEY (event_id, occurred_at)
) PARTITION BY RANGE (occurred_at);

CREATE TABLE events_2026_01 PARTITION OF events
FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE events_2026_02 PARTITION OF events
FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

INSERT INTO events (occurred_at, payload)
SELECT
    '2026-01-01'::timestamptz + (number || ' minutes')::interval,
    repeat('january-', 20)
FROM generate_series(1, 1000) AS number;

INSERT INTO events (occurred_at, payload)
SELECT
    '2026-02-01'::timestamptz + (number || ' minutes')::interval,
    repeat('february-', 20)
FROM generate_series(1, 1000) AS number;
