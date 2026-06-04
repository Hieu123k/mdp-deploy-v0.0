"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import {
  ApiError,
  createReferenceOption,
  deleteReferenceOption,
  getReferenceList,
  updateReferenceOption,
  type ReferenceOption,
} from "@/lib/api";
import { Select } from "./Select";

/**
 * A <Select> bound to an admin-editable reference list. Any authenticated user sees the
 * options; an admin gets an inline "manage" panel to add / edit / delete them (persisted via
 * /reference/{listKey}). Drop-in replacement for a hard-coded constant dropdown.
 */
export function EditableSelect({
  listKey,
  label,
  value,
  onChange,
  includeEmpty,
  disabled,
  format,
}: {
  listKey: string;
  label?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  includeEmpty?: string;
  disabled?: boolean;
  format?: (value: string) => string;
}) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [options, setOptions] = useState<ReferenceOption[]>([]);
  const [managing, setManaging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await getReferenceList(listKey);
      setOptions(r.options);
    } catch {
      /* keep previous options on transient failure */
    }
  }, [listKey]);

  useEffect(() => {
    load();
  }, [load]);

  // Make sure the current value is selectable even if it isn't (yet) in the list.
  const hasValue = value === "" || options.some((o) => o.value === value);

  return (
    <div>
      <div className="flex items-end gap-1.5">
        <div className="min-w-0 flex-1">
          <Select label={label} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
            {includeEmpty !== undefined && <option value="">{includeEmpty}</option>}
            {!hasValue && value && <option value={value}>{format ? format(value) : value}</option>}
            {options.map((o) => (
              <option key={o.id} value={o.value}>
                {o.label || (format ? format(o.value) : o.value)}
              </option>
            ))}
          </Select>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={() => setManaging((m) => !m)}
            title="Manage options (admin)"
            className="mb-0.5 inline-flex h-10 items-center rounded-md border border-neutral-300 px-2 text-neutral-600 hover:bg-neutral-100"
          >
            <Pencil size={14} />
          </button>
        )}
      </div>
      {isAdmin && managing && (
        <ManagePanel listKey={listKey} options={options} onChanged={load} onError={setError} />
      )}
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}

// Defined at module scope (NOT inside EditableSelect) so its inputs keep focus while typing.
function ManagePanel({
  listKey,
  options,
  onChanged,
  onError,
}: {
  listKey: string;
  options: ReferenceOption[];
  onChanged: () => void | Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [newValue, setNewValue] = useState("");
  const [editId, setEditId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const fail = (e: unknown, fallback: string) =>
    onError(e instanceof ApiError ? e.message : fallback);

  const add = async () => {
    const v = newValue.trim();
    if (!v) return;
    onError(null);
    try {
      await createReferenceOption(listKey, { value: v, label: v });
      setNewValue("");
      await onChanged();
    } catch (e) {
      fail(e, "Add failed");
    }
  };

  const saveEdit = async (id: string) => {
    const v = editValue.trim();
    if (!v) return;
    onError(null);
    try {
      await updateReferenceOption(listKey, id, { value: v, label: v });
      setEditId(null);
      await onChanged();
    } catch (e) {
      fail(e, "Update failed");
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("Delete this option?")) return;
    onError(null);
    try {
      await deleteReferenceOption(listKey, id);
      await onChanged();
    } catch (e) {
      fail(e, "Delete failed");
    }
  };

  return (
    <div className="mt-1.5 rounded-md border border-neutral-200 bg-neutral-50 p-2 text-xs">
      <div className="mb-1 font-medium text-neutral-600">Manage options · {listKey}</div>
      <div className="max-h-48 space-y-1 overflow-y-auto">
        {options.map((o) => (
          <div key={o.id} className="flex items-center gap-1">
            {editId === o.id ? (
              <>
                <input
                  className="h-7 min-w-0 flex-1 rounded border border-neutral-300 px-2"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  autoFocus
                />
                <IconBtn title="Save" onClick={() => saveEdit(o.id)}><Check size={13} /></IconBtn>
                <IconBtn title="Cancel" onClick={() => setEditId(null)}><X size={13} /></IconBtn>
              </>
            ) : (
              <>
                <span className="min-w-0 flex-1 truncate">{o.label || o.value}</span>
                <IconBtn title="Edit" onClick={() => { setEditId(o.id); setEditValue(o.value); }}><Pencil size={12} /></IconBtn>
                <IconBtn title="Delete" onClick={() => remove(o.id)}><Trash2 size={12} /></IconBtn>
              </>
            )}
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex items-center gap-1">
        <input
          className="h-7 min-w-0 flex-1 rounded border border-neutral-300 px-2"
          placeholder="New option…"
          value={newValue}
          onChange={(e) => setNewValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
        />
        <button
          type="button"
          onClick={add}
          className="inline-flex h-7 items-center gap-1 rounded bg-brand px-2 text-white hover:bg-brand/90"
        >
          <Plus size={12} /> Add
        </button>
      </div>
    </div>
  );
}

function IconBtn({ title, onClick, children }: { title: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded border border-neutral-300 text-neutral-600 hover:bg-neutral-100"
    >
      {children}
    </button>
  );
}
