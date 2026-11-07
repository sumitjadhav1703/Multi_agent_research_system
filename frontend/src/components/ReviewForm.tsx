import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { cancelRun, reviewRun } from "../api/client";
import { useToken } from "../auth/token";
import { ErrorText } from "./ui";

export function ReviewForm({ runId }: { runId: string }) {
  const { token } = useToken();
  const queryClient = useQueryClient();
  const [comments, setComments] = useState("");
  const mutation = useMutation({
    mutationFn: (action: "approve" | "revise" | "reject") => reviewRun(token ?? "", runId, action, comments),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  return (
    <form className="panel stack" aria-label="Human review">
      <h2>Human review</h2>
      <p>One revision can be requested. Approval and rejection are final for this run.</p>
      <label className="field">
        <span>Comments</span>
        <textarea
          value={comments}
          maxLength={2000}
          onChange={(event) => setComments(event.target.value)}
        />
      </label>
      <p className="meta">{comments.length} / 2000</p>
      <ErrorText error={mutation.error} />
      <div className="button-row">
        <button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate("approve")}>
          Approve
        </button>
        <button type="button" className="secondary" disabled={mutation.isPending} onClick={() => mutation.mutate("revise")}>
          Request one revision
        </button>
        <button type="button" className="secondary" disabled={mutation.isPending} onClick={() => mutation.mutate("reject")}>
          Reject
        </button>
      </div>
    </form>
  );
}

export function CancelRun({ runId }: { runId: string }) {
  const { token } = useToken();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    mutationFn: () => cancelRun(token ?? "", runId),
    onSuccess: async () => {
      setConfirming(false);
      await queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  return (
    <div className="panel stack">
      <h2>Stop</h2>
      <p>Cancelling uses the one-use demo run. It does not start another one.</p>
      {confirming ? (
        <div className="button-row">
          <button type="button" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            Confirm cancel
          </button>
          <button type="button" className="secondary" onClick={() => setConfirming(false)}>
            Keep running
          </button>
        </div>
      ) : (
        <button type="button" className="secondary" onClick={() => setConfirming(true)}>
          Cancel run
        </button>
      )}
      <ErrorText error={mutation.error} />
    </div>
  );
}
