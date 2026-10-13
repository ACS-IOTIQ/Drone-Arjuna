import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";
import { api } from "@/api/client";

interface Dump {
  name: string;
  size: number;
  modified: string;
  source: "minio" | "local";
}

type Backups = Record<string, Dump[]>;

export default function BackupManager() {
  const [data, setData] = useState<Backups>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<Backups>("/api/system/backup/list")
      .then(({ data }) => setData(data))
      .catch((e) => setMsg(e?.response?.data?.detail ?? "Failed to load backups"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const restore = async (database: string) => {
    if (!window.confirm(`Restore empty ${database} tables from the latest backup?`)) return;
    setBusy(true);
    setMsg(null);
    try {
      const { data } = await api.post("/api/system/backup/restore", { confirm: true, database });
      const done = Object.entries(data.restored).filter(([, v]) => v).map(([k]) => k);
      setMsg(done.length ? `Restored: ${done.join(", ")}` : "Nothing to restore — tables already contain data.");
    } catch (e: any) {
      setMsg(e?.response?.data?.detail ?? "Restore failed");
    } finally {
      setBusy(false);
      load();
    }
  };

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Database Backups</h2>
        <button className="da-btn flex items-center gap-1 text-sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      {msg && <div className="da-card p-3 text-sm">{msg}</div>}
      {loading && <p className="text-sm">Loading…</p>}
      {Object.entries(data).map(([db, dumps]) => (
        <div key={db} className="da-card p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium capitalize">{db} database ({dumps.length})</h3>
            <button
              className="da-btn flex items-center gap-1 text-sm"
              disabled={busy || dumps.length === 0}
              onClick={() => restore(db)}
            >
              <RotateCcw size={14} /> Restore latest
            </button>
          </div>
          {dumps.length === 0 ? (
            <p className="text-sm">No backups found.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th>File</th>
                  <th>Created</th>
                  <th>Size</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {dumps.map((d) => (
                  <tr key={d.name}>
                    <td>{d.name}</td>
                    <td>{new Date(d.modified).toLocaleString()}</td>
                    <td>{(d.size / 1024).toFixed(1)} KB</td>
                    <td>{d.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}
