import type { ArtifactSnapshot, ConnectionState, RunEvent } from "../api/types";
import { mergeEvents } from "../domain/runView";

export interface RunEntry {
  events: RunEvent[];
  snapshot: ArtifactSnapshot | null;
  connection: ConnectionState;
}

type Listener = () => void;

class RunStore {
  private entries = new Map<string, RunEntry>();
  private listeners = new Set<Listener>();
  private version = 0;

  subscribe = (listener: Listener) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getVersion = () => this.version;

  get(runId: string): RunEntry | undefined {
    return this.entries.get(runId);
  }

  merge(runId: string, incoming: readonly RunEvent[]) {
    const current = this.entry(runId);
    const events = mergeEvents(current.events, incoming);
    if (
      events.length === current.events.length &&
      events.every((event, index) => event.sequence_id === current.events[index]?.sequence_id)
    ) {
      return;
    }
    this.entries.set(runId, { ...current, events });
    this.emit();
  }

  setSnapshot(runId: string, snapshot: ArtifactSnapshot) {
    const current = this.entry(runId);
    if (JSON.stringify(current.snapshot) === JSON.stringify(snapshot)) return;
    this.entries.set(runId, { ...current, snapshot });
    this.emit();
  }

  setConnection(runId: string, connection: ConnectionState) {
    const current = this.entry(runId);
    if (current.connection === connection) return;
    this.entries.set(runId, { ...current, connection });
    this.emit();
  }

  clear() {
    this.entries.clear();
    this.emit();
  }

  private entry(runId: string): RunEntry {
    return this.entries.get(runId) ?? { events: [], snapshot: null, connection: "idle" };
  }

  private emit() {
    this.version += 1;
    for (const listener of this.listeners) listener();
  }
}

export const runStore = new RunStore();

export function resetRunStore() {
  runStore.clear();
}
