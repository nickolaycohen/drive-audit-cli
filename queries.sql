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