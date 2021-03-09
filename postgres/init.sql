CREATE TABLE IF NOT EXISTS public.users (
	user_id int8 NOT NULL,
	api_key text NOT NULL,
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
AS SELECT ph.x,
    ph.y,
    ph.pixel_history_id,
    ph.rgb
   FROM ( SELECT pixel_history.pixel_history_id,
            max(pixel_history.created_at) AS created_at
           FROM pixel_history
          WHERE NOT pixel_history.deleted
          GROUP BY pixel_history.x, pixel_history.y, pixel_history.pixel_history_id, pixel_history.created_at) most_recent_pixels
     JOIN pixel_history ph USING (pixel_history_id, created_at);
