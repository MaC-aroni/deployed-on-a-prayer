import { useEffect } from "react";
import { approvalOutstanding } from "./util.js";

// While any approval is still outstanding, re-fetch the migration every few seconds so an approval
// given in Jira shows up without a reload. `reload` should only fetch GET /migrations/{name}: that
// is a read of MaC's own records (the server talks to Jira, by webhook and its own poller), so it
// is cheap. Pauses while the tab is hidden and catches up the moment it's visible again.
export function useLiveApprovals(approvals, reload, seconds = 5) {
  const outstanding = (approvals || []).some(approvalOutstanding);
  useEffect(() => {
    if (!outstanding) return undefined;
    const tick = () => { if (document.visibilityState === "visible") reload(); };
    const timer = setInterval(tick, seconds * 1000);
    return () => clearInterval(timer);
  }, [outstanding, reload, seconds]);
}
