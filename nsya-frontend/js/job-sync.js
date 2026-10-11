import { getJob } from "./api.js";
import { mergeSubjects, setJobDone, getState } from "./store.js";

/**
 * Keeps the local store in sync with the backend job while it is still
 * running, so subject/unit/topic names and generation status update live on
 * whatever screen the learner happens to be on. Call this once per screen
 * and invoke the returned function on cleanup.
 */
export function useJobSync(intervalMs = 2000) {
  let alive = true;
  let timer = null;

  const tick = async (isFirst = false) => {
    const { jobId, jobDone } = getState();
    if (!jobId) return;
    // A finished job still gets ONE fetch per screen mount, then stops.
    // The backend stores each topic's completion + accuracy durably (see
    // POST /topics/{id}/complete), and mergeSubjects only ever upgrades
    // local progress, never clears it - so this is what brings progress
    // recorded elsewhere (another browser, or this one after its
    // localStorage copy was lost) back into view. Without it the store's
    // own cache was the only source of progress after a job finished.
    if (jobDone && !isFirst) return;
    try {
      const job = await getJob(jobId);
      if (!alive) return;
      if (job.subjects?.length) mergeSubjects(job.subjects);
      if (job.status === "done" || job.status === "error") {
        setJobDone(true);
        return;
      }
    } catch {
      /* transient — keep polling */
    }
    if (alive && !getState().jobDone) timer = setTimeout(tick, intervalMs);
  };

  tick(true);

  return () => {
    alive = false;
    clearTimeout(timer);
  };
}
