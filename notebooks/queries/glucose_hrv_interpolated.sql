-- Glucose x HRV (interpolated) for one study subject.
--
-- Aligns overnight HRV onto the dense continuous-glucose (CGM) timeline by
-- linear interpolation between the nearest HRV readings. Glucose is the dense
-- series, so we keep one row per glucose reading and attach an interpolated
-- HRV value.
--
-- Parameters:
--   @user  STRING  -- subject user_id (e.g. 'vincent')
-- Substitutions:
--   PROJECT_PLACEHOLDER  -> GCP project id (done in the notebook)
--
-- NOTE: Garmin HRV is measured only during sleep, so daytime glucose rows get
-- an HRV value interpolated across the overnight gaps — read daytime HRV here
-- as "bridged between nights", not a real waking measurement.

WITH glucose AS (
  SELECT @user AS user_id, ts, glucose_mg_dl
  FROM `PROJECT_PLACEHOLDER.health_twin.glucose`
  WHERE user_id = @user
),
hrv AS (
  SELECT @user AS user_id, ts AS hrv_ts, CAST(hrv_value AS FLOAT64) AS hrv_value
  FROM `PROJECT_PLACEHOLDER.health_twin.hrv_readings`
  WHERE user_id = @user
),
combined AS (
  SELECT user_id, ts, glucose_mg_dl,
    CAST(NULL AS STRUCT<ts TIMESTAMP, val FLOAT64>) AS hrv_point
  FROM glucose
  UNION ALL
  SELECT user_id, hrv_ts AS ts, CAST(NULL AS FLOAT64) AS glucose_mg_dl,
    STRUCT(hrv_ts AS ts, hrv_value AS val) AS hrv_point
  FROM hrv
),
with_neighbors AS (
  SELECT
    user_id,
    ts,
    glucose_mg_dl,
    LAST_VALUE(hrv_point IGNORE NULLS) OVER (
      PARTITION BY user_id ORDER BY ts
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS prev_hrv,
    FIRST_VALUE(hrv_point IGNORE NULLS) OVER (
      PARTITION BY user_id ORDER BY ts
      ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
    ) AS next_hrv
  FROM combined
)
SELECT
  user_id,
  ts,
  glucose_mg_dl,
  prev_hrv.val AS prev_hrv_val,
  prev_hrv.ts  AS prev_hrv_ts,
  next_hrv.val AS next_hrv_val,
  next_hrv.ts  AS next_hrv_ts,
  CASE
    -- exact match on a real HRV row
    WHEN prev_hrv.ts = ts THEN prev_hrv.val
    -- both neighbors exist -> linear interpolation
    WHEN prev_hrv.val IS NOT NULL AND next_hrv.val IS NOT NULL THEN
      prev_hrv.val + (next_hrv.val - prev_hrv.val)
        * TIMESTAMP_DIFF(ts, prev_hrv.ts, SECOND)
        / NULLIF(TIMESTAMP_DIFF(next_hrv.ts, prev_hrv.ts, SECOND), 0)
    -- no future point yet (most recent data) -> carry forward
    WHEN prev_hrv.val IS NOT NULL THEN prev_hrv.val
    -- no past point yet (very start of series) -> carry backward
    ELSE next_hrv.val
  END AS hrv_interpolated
FROM with_neighbors
WHERE glucose_mg_dl IS NOT NULL   -- keep only glucose rows, the dense timeline
ORDER BY ts
