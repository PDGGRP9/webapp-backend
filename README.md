# Webapp backend

Back-end Django JSON pour l’infra actuelle. Il expose une API simple branchée sur PostgreSQL, avec un flux d’authentification JWT léger et une ingestion directe des mesures en HTTP.

## Démarrage local

```sh
cd webapp-backend/backend
python3 -m pip install -r requirements.txt
python3 manage.py check
python3 manage.py test
python3 manage.py migrate
python3 manage.py runserver 0.0.0.0:8000
```

Si les variables `DB_HOST`, `DB_NAME`, `DB_USER` et `DB_PASSWORD` sont définies, Django se connecte à PostgreSQL. Sinon il retombe sur SQLite pour le développement local.

## Routes API

### Santé

GET /api/
GET /api/health

### Auth

POST /api/register
POST /api/login
POST /api/logout
GET /api/me

`/api/register` crée un utilisateur minimal. `/api/login` renvoie un token signé que le front peut garder côté client. `/api/logout` est volontairement stateless pour rester simple à consommer par web et Android. `/api/me` (Bearer token requis) renvoie l'utilisateur courant ou 401 si le token est absent/expiré/invalide — utilisé par le front pour valider une session stockée avant d'afficher l'app.

`/api/login` accepte aussi bien les mots de passe hashés par Django (`/api/register`, PBKDF2) que les hashs bcrypt bruts (`$2a$`/`$2b$`) que le seed d'`infra-db` écrit via `pgcrypto`/`crypt()` — ces deux formats de hash ne s'auto-détectent pas de la même façon, voir `_verify_password` dans `api/views.py`.

### Données personnelles (RGPD)

DELETE /api/me/data
GET /api/me/data/export

`/api/me/data` (Bearer token requis) supprime définitivement toutes les mesures biométriques de l'utilisateur authentifié. Action irréversible.

`/api/me/data/export` (Bearer token requis) exporte le profil et les mesures de l'utilisateur authentifié. Paramètre `?format=json` (défaut) ou `?format=csv` ; la réponse est envoyée en pièce jointe (`Content-Disposition: attachment`). En CSV, une colonne par attribut, séparateur `;` (et BOM UTF-8) pour être lisible directement par Excel FR. En JSON, `{"user": {...}, "measurements": [{...}, ...]}` où chaque mesure est un objet plat regroupant tous ses champs (mêmes champs que les colonnes CSV, y compris les infos de l'appareil préfixées `bracelet_*`).

### Mesures

POST /api/datas
GET /api/datas/{userId}
GET /api/statistics/{userId}

Il n'y a pas de table/appairage de bracelets : une mesure appartient directement à l'utilisateur authentifié, et le lien BLE ne parle jamais qu'à un seul bracelet à la fois. `POST /api/datas` (Bearer token requis) attache la mesure à qui possède le token — `device_uid`/`serial_number`/`display_name`/`mac_address` ne sont que des colonnes descriptives sur la mesure elle-même (quel appareil a produit ce relevé), pas une clé étrangère : un utilisateur peut poster depuis autant de bracelets physiques différents qu'il veut, rien à appairer ni désappairer. `GET /api/datas/{userId}` liste les mesures d'un utilisateur, et `GET /api/statistics/{userId}` expose des agrégats simples.

## Contrat POST /api/datas

Authentification Bearer requise (`Authorization: Bearer <token>`) — la mesure est attribuée au propriétaire du token, pas à un `user_id` du payload.

Champs recommandés (tous optionnels, purement descriptifs) :

- `device_uid`
- `serial_number`
- `display_name`
- `mac_address`
- `captured_at`
- `heart_rate_bpm`
- `spo2_percent`
- `step_count`
- `motion_level`
- `signal_quality`
- `source_topic`
- `raw_payload`
- `samples`

Le back-end stocke l’objet complet dans `raw_payload` et conserve les champs biométriques normalisés pour les requêtes et statistiques.