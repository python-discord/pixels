CREATE TABLE IF NOT EXISTS public.cache_state (
    Lock char(1) not null DEFAULT 'X',
    last_modified timestamp NOT NULL DEFAULT now(),
    last_synced timestamp NOT NULL DEFAULT now() - interval '1 day',
    sync_lock timestamp NULL DEFAULT NULL,
    constraint PK_T1 PRIMARY KEY (Lock),
    constraint CK_T1_Locked CHECK (Lock='X')
);
INSERT INTO cache_state DEFAULT VALUES ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.users (
	user_id int8 NOT NULL,
	key_salt text NOT NULL,
	is_mod bool NOT NULL DEFAULT false,
	is_banned bool NOT NULL DEFAULT false,
	CONSTRAINT users_pk PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS  public.pixel_history (
	pixel_history_id serial NOT NULL,
	created_at TIMESTAMP NOT NULL DEFAULT now(),
	x int2 NOT NULL,
	y int2 NOT NULL,
	rgb varchar(6) NOT NULL,
	user_id int8 NOT NULL,
	deleted bool NOT NULL,
	CONSTRAINT pixel_history_pk PRIMARY KEY (pixel_history_id)
);

ALTER TABLE public.pixel_history ADD CONSTRAINT pixel_history_fk FOREIGN KEY (user_id) REFERENCES users(user_id);

CREATE OR REPLACE VIEW public.current_pixel
AS SELECT PH.x,
          PH.y,
          PH.pixel_history_id,
          PH.rgb
FROM (
    SELECT MAX(pixel_history_id) as pixel_history_id
    FROM pixel_history
    WHERE NOT deleted
    GROUP BY x, y
) most_recent_pixels
INNER JOIN pixel_history PH USING (pixel_history_id);

CREATE OR REPLACE FUNCTION update_timestamp() RETURNS TRIGGER AS $update_timestamp$
    BEGIN
        UPDATE cache_state SET last_modified = now();
        RETURN NULL;
    END;
$update_timestamp$ LANGUAGE plpgsql;

CREATE TRIGGER cache_state
    AFTER INSERT OR UPDATE OR DELETE ON pixel_history
    EXECUTE FUNCTION update_timestamp();
