import { cx } from "../lib.js";

// Loading placeholders in the shape of what is coming, instead of a "Loading…" line.
export function Skeleton({ w = "100%", h = 14, className, style }) {
  return <span className={cx("skeleton", className)} style={{ width: w, height: h, ...style }} aria-hidden />;
}

export function SkeletonRows({ rows = 4, cols = 4 }) {
  return (
    <div className="table skeleton-table" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div className="tr" key={i}>
          {Array.from({ length: cols }, (_, j) => (
            <div key={j}>
              <Skeleton w={j === 1 ? "70%" : "55%"} h={j === 1 ? 16 : 12} />
              {j === 1 && <Skeleton w="40%" h={10} style={{ marginTop: 8 }} />}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonPage({ rows = 5, cols = 4, title = true }) {
  return (
    <>
      {title && (
        <div className="page-head">
          <Skeleton w={220} h={26} />
          <Skeleton w="60%" h={12} style={{ marginTop: 12 }} />
        </div>
      )}
      <SkeletonRows rows={rows} cols={cols} />
    </>
  );
}

export function SkeletonPipeline() {
  return (
    <div className="dag-frame skeleton-dag" aria-busy="true" aria-label="Loading pipeline">
      {Array.from({ length: 5 }, (_, i) => (
        <div className="skeleton-col" key={i}>
          <Skeleton w={90} h={10} />
          {Array.from({ length: i % 2 ? 2 : 1 }, (_, j) => (
            <Skeleton key={j} w={300} h={80} style={{ borderRadius: 12 }} />
          ))}
        </div>
      ))}
    </div>
  );
}
