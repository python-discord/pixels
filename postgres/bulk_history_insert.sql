INSERT INTO public.users
SELECT user.id, 'secret_key', 't', 'f'
FROM generate_series(1, 100) as user(id)
ON CONFLICT DO NOTHING;

ALTER TABLE public.pixel_history DROP CONSTRAINT pixel_history_fk;

COPY public.pixel_history(x, y, rgb, user_id, deleted) FROM '/scripts/test_data.csv' DELIMITER ',' CSV HEADER;

ALTER TABLE public.pixel_history ADD CONSTRAINT pixel_history_fk FOREIGN KEY (user_id) REFERENCES users(user_id);
