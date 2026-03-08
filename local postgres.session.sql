SELECT * FROM rn_licenses WHERE NAME LIKE 'X%';
SELECT LEFT(name, 1) AS letter, COUNT(*)
FROM rn_licenses
GROUP BY letter
ORDER BY letter;

SELECT * FROM users;
SELECT current_database();

