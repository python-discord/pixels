insert into public.users values (-1, 'secret_key', 't', 'f');

ALTER TABLE public.pixel_history DROP CONSTRAINT pixel_history_fk;

COPY public.pixel_history(x, y, rgb, user_id, deleted) FROM '/scripts/test_data.csv' DELIMITER ',' CSV HEADER;

ALTER TABLE public.pixel_history ADD CONSTRAINT pixel_history_fk FOREIGN KEY (user_id) REFERENCES users(user_id);
