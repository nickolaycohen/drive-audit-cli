-- largest files with tags - locate duplicates and non-tagged items - probably to be moved to the /Volumes/LaCie/Storage and correct priority
WITH top_files AS (
    SELECT 
        f.id AS file_id,
        f.directory_id,
        f.name,
        f.category,
        f.modified_at,
        f.size_bytes,
        ROUND(f.size_bytes / 1024.0 / 1024.0, 2) AS size_mb
    FROM files f
    ORDER BY f.size_bytes DESC
    LIMIT 400
)
SELECT 
    tf.name,
    tf.category,
    tf.modified_at,
    tf.size_mb,
    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') AS folder_tags,
    COALESCE(GROUP_CONCAT(DISTINCT ft.tag_name), '-') AS file_tags,
    d.path || '/' || tf.name AS full_path,
    h.hostname
FROM top_files tf
JOIN directories d ON tf.directory_id = d.id
JOIN hosts h ON d.host_id = h.id
LEFT JOIN directory_tags dt ON d.id = dt.directory_id
LEFT JOIN file_tags ft ON tf.file_id = ft.file_id
GROUP BY tf.file_id
ORDER BY tf.size_bytes DESC;

-- all assets with GPS exif data
SELECT 
    d.path AS folder_path,
    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') AS folder_tags,
    COUNT(f.id) AS gps_photos_count,
    ROUND(SUM(f.size_bytes) / 1024.0 / 1024.0, 2) AS total_mb,
    MIN(m.date_taken) AS earliest_shot,
    MAX(m.date_taken) AS latest_shot
FROM media_metadata m
JOIN files f ON m.file_id = f.id
JOIN directories d ON f.directory_id = d.id
LEFT JOIN directory_tags dt ON d.id = dt.directory_id
WHERE m.gps_latitude IS NOT NULL 
  AND m.gps_latitude != ''
GROUP BY d.id
ORDER BY gps_photos_count DESC
LIMIT 25;

-- all cameras assets
SELECT 
    COALESCE(m.camera_make, 'Unknown Make') AS camera_make,
    COALESCE(m.camera_model, 'Unknown Model') AS camera_model,
    COUNT(f.id) AS photo_count,
    ROUND(SUM(f.size_bytes) / 1024.0 / 1024.0, 2) AS total_mb,
    ROUND(SUM(f.size_bytes) / 1024.0 / 1024.0 / 1024.0, 2) AS total_gb,
    MIN(m.date_taken) AS earliest_shot,
    MAX(m.date_taken) AS latest_shot
FROM media_metadata m
JOIN files f ON m.file_id = f.id
GROUP BY m.camera_make, m.camera_model
ORDER BY photo_count DESC;



-- global waste 
SELECT 
    COUNT(*) AS duplicate_groups,
    SUM(copy_count) AS total_duplicate_files,
    SUM(copy_count - 1) AS redundant_copies,
    ROUND(SUM((copy_count - 1) * size_bytes) / 1024.0 / 1024.0 / 1024.0, 2) AS recoverable_gb
FROM (
    SELECT name, size_bytes, COUNT(*) AS copy_count
    FROM files
    WHERE size_bytes > 0
    GROUP BY name, size_bytes
    HAVING COUNT(*) > 1
);


-- all dups by size
WITH duplicate_candidates AS (
    SELECT 
        f.id AS file_id,
        f.directory_id,
        f.name,
        f.category,
        f.size_bytes,
        f.modified_at,
        COUNT(*) OVER(PARTITION BY f.name, f.size_bytes) AS copy_count,
        DENSE_RANK() OVER(ORDER BY f.size_bytes DESC, f.name) AS group_rank
    FROM files f
    WHERE f.size_bytes > 0
)
SELECT 
    dc.group_rank,
    dc.name,
    dc.category,
    ROUND(dc.size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
    dc.copy_count,
    dc.modified_at,
    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') AS folder_tags,
    COALESCE(GROUP_CONCAT(DISTINCT ft.tag_name), '-') AS file_tags,
    d.path || '/' || dc.name AS full_path,
    h.hostname
FROM duplicate_candidates dc
JOIN directories d ON dc.directory_id = d.id
JOIN hosts h ON d.host_id = h.id
LEFT JOIN directory_tags dt ON d.id = dt.directory_id
LEFT JOIN file_tags ft ON dc.file_id = ft.file_id
WHERE dc.copy_count > 1
GROUP BY dc.file_id
ORDER BY dc.size_bytes DESC, dc.group_rank, d.path
LIMIT 50;



-- recursive list of top level folders
WITH TopRoots AS (
    -- 1. Identify all top-level root folders (folders not nested inside any other scanned folder)
    SELECT 
        d.id,
        d.path,
        d.host_id,
        h.hostname,
        d.scanned_at
    FROM directories d
    JOIN hosts h ON d.host_id = h.id
    WHERE NOT EXISTS (
        SELECT 1 
        FROM directories parent 
        WHERE parent.host_id = d.host_id 
          AND parent.id != d.id 
          AND d.path LIKE parent.path || '/%'
    )
),
SubtreeFiles AS (
    -- 2. Aggregate file count and exact byte sum across all descendant subdirectories
    SELECT 
        tr.id AS root_id,
        COUNT(DISTINCT d_sub.id) AS total_subfolders,
        COUNT(f.id) AS total_files,
        COALESCE(SUM(f.size_bytes), 0) AS total_bytes
    FROM TopRoots tr
    JOIN directories d_sub 
      ON d_sub.host_id = tr.host_id 
     AND (d_sub.path = tr.path OR d_sub.path LIKE tr.path || '/%')
    LEFT JOIN files f 
      ON f.directory_id = d_sub.id
    GROUP BY tr.id
),
SubtreeTags AS (
    -- 3. Collect distinct tags present anywhere across the subtree
    SELECT 
        tr.id AS root_id,
        GROUP_CONCAT(DISTINCT dt.tag_name) AS subtree_tags
    FROM TopRoots tr
    JOIN directories d_sub 
      ON d_sub.host_id = tr.host_id 
     AND (d_sub.path = tr.path OR d_sub.path LIKE tr.path || '/%')
    JOIN directory_tags dt 
      ON dt.directory_id = d_sub.id
    GROUP BY tr.id
),
RootDirectTags AS (
    -- 4. Collect tags directly attached to the root folder itself
    SELECT 
        tr.id AS root_id,
        GROUP_CONCAT(dt.tag_name, ', ') AS root_tags
    FROM TopRoots tr
    JOIN directory_tags dt ON dt.directory_id = tr.id
    GROUP BY tr.id
)
SELECT 
    tr.path AS root_path,
    tr.hostname,
    COALESCE(rdt.root_tags, '(none)') AS direct_root_tags,
    COALESCE(st.subtree_tags, '(none)') AS all_subtree_tags,
    sf.total_subfolders,
    sf.total_files,
    ROUND(sf.total_bytes / 1024.0 / 1024.0, 2) AS size_mb,
    ROUND(sf.total_bytes / 1024.0 / 1024.0 / 1024.0, 2) AS size_gb,
    tr.scanned_at AS last_scanned
FROM TopRoots tr
JOIN SubtreeFiles sf ON sf.root_id = tr.id
LEFT JOIN SubtreeTags st ON st.root_id = tr.id
LEFT JOIN RootDirectTags rdt ON rdt.root_id = tr.id
ORDER BY sf.total_bytes DESC;

-- basic list of top level scanned folders
SELECT 
    d.id,
    d.path AS root_path,
    h.hostname,
    d.scanned_at
FROM directories d
JOIN hosts h ON d.host_id = h.id
WHERE NOT EXISTS (
    SELECT 1 
    FROM directories parent 
    WHERE parent.host_id = d.host_id 
      AND parent.id != d.id 
      AND d.path LIKE parent.path || '/%'
)
ORDER BY d.path;

-- detailed list of top level scanned folders
WITH TopRoots AS (
    SELECT 
        d.id,
        d.path,
        d.host_id,
        h.hostname,
        d.scanned_at
    FROM directories d
    JOIN hosts h ON d.host_id = h.id
    WHERE NOT EXISTS (
        SELECT 1 
        FROM directories parent 
        WHERE parent.host_id = d.host_id 
          AND parent.id != d.id 
          AND d.path LIKE parent.path || '/%'
    )
)
SELECT 
    tr.path AS root_path,
    tr.hostname,
    tr.scanned_at AS last_scanned,
    COUNT(DISTINCT d_sub.id) AS total_subfolders,
    COUNT(f.id) AS total_files,
    ROUND(COALESCE(SUM(f.size_bytes), 0) / 1024.0 / 1024.0, 2) AS size_mb,
    ROUND(COALESCE(SUM(f.size_bytes), 0) / 1024.0 / 1024.0 / 1024.0, 2) AS size_gb
FROM TopRoots tr
JOIN directories d_sub 
  ON d_sub.host_id = tr.host_id 
 AND (d_sub.path = tr.path OR d_sub.path LIKE tr.path || '/%')
LEFT JOIN files f 
  ON f.directory_id = d_sub.id
GROUP BY tr.id, tr.path
ORDER BY size_gb DESC;


-- largest files
SELECT 
    f.name,
    f.category,
    --f.size_bytes,
    -- ROUND(f.size_bytes / 1024.0, 2) AS size_kb,
    f.modified_at,
    ROUND(f.size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
    d.path || '/' || f.name AS full_path,
    h.hostname
FROM files f
JOIN directories d ON f.directory_id = d.id
JOIN hosts h ON d.host_id = h.id
ORDER BY f.size_bytes DESC
LIMIT 20;

-- largest folders
SELECT 
    parent_host.hostname,
    parent.path,
    parent.name,
    COUNT(f.id) AS total_files,
    ROUND(SUM(f.size_bytes) / 1024.0 / 1024.0, 2) AS total_size_mb,
    ROUND(SUM(f.size_bytes) / 1024.0 / 1024.0 / 1024.0, 3) AS total_size_gb
FROM directories parent	
JOIN hosts parent_host ON parent.host_id = parent_host.id
JOIN directories child 
  ON child.host_id = parent.host_id 
 AND (child.path = parent.path OR SUBSTR(child.path, 1, LENGTH(parent.path) + 1) = parent.path || '/')
JOIN files f ON f.directory_id = child.id
GROUP BY parent.id
ORDER BY SUM(f.size_bytes) DESC
LIMIT 20;


select * 
from directories d 