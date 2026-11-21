"""Initialize or upgrade Jumpseat using the operator's migration identity."""

import os

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from ifdispatcher.core import PG_SCHEMA
from ifdispatcher.siwc import CREDENTIAL_DDL


def migrate(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        for statement in (*PG_SCHEMA, CREDENTIAL_DDL):
            conn.execute(statement)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paid_policy (
                id boolean PRIMARY KEY CHECK (id),
                stopped boolean NOT NULL DEFAULT true,
                daily_pages integer NOT NULL DEFAULT 0 CHECK (daily_pages >= 0)
            )
        """)
        conn.execute("INSERT INTO paid_policy (id) VALUES (true) ON CONFLICT DO NOTHING")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS aeroapi_usage (
                day date PRIMARY KEY, pages integer NOT NULL CHECK (pages >= 0)
            )
        """)
        conn.execute("""
            CREATE OR REPLACE FUNCTION public.stop_jumpseat() RETURNS boolean
            LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
                UPDATE public.paid_policy SET stopped = true WHERE id RETURNING stopped
            $$
        """)
        conn.execute("REVOKE ALL ON FUNCTION public.stop_jumpseat() FROM PUBLIC")
        conn.execute("""
            CREATE OR REPLACE FUNCTION public.reserve_aeroapi_pages(units integer) RETURNS text
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
            DECLARE policy public.paid_policy%ROWTYPE;
            BEGIN
                SELECT * INTO policy FROM public.paid_policy WHERE id FOR SHARE;
                IF NOT FOUND OR policy.stopped THEN RETURN 'paid_operations_disabled'; END IF;
                IF units IS NULL OR units < 1 OR units > policy.daily_pages THEN
                    RETURN 'daily_aeroapi_allowance_exhausted';
                END IF;
                INSERT INTO public.aeroapi_usage AS usage (day, pages)
                    VALUES ((clock_timestamp() AT TIME ZONE 'UTC')::date, units)
                    ON CONFLICT (day) DO UPDATE SET pages = usage.pages + excluded.pages
                    WHERE usage.pages <= policy.daily_pages - excluded.pages;
                IF NOT FOUND THEN RETURN 'daily_aeroapi_allowance_exhausted'; END IF;
                RETURN 'reserved';
            END $$
        """)
        conn.execute("REVOKE ALL ON FUNCTION public.reserve_aeroapi_pages(integer) FROM PUBLIC")
    with PostgresSaver.from_conn_string(dsn) as saver:
        saver.setup()


if __name__ == "__main__":
    migrate(os.environ["IFD_MIGRATION_DATABASE_URL"])
