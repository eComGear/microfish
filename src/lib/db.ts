import { Pool } from "pg";

// DATABASE_URL points to Supabase Postgres or fly Postgres.
// Use the connection-pooler URL for the API process; workers can use direct.
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 10,
  ssl: process.env.DATABASE_SSL === "false" ? false : { rejectUnauthorized: false },
});

export async function query<T = any>(sql: string, params: any[] = []) {
  const res = await pool.query(sql, params);
  return res.rows as T[];
}
