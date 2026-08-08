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

`/api/register` crée un utilisateur minimal. `/api/login` renvoie un token signé que le front peut garder côté client. `/api/logout` est volontairement stateless pour rester simple à consommer par web et Android.

### Bracelets

POST /api/bracelets/pair
GET /api/bracelets/{userId}

`/api/bracelets/pair` rattache un bracelet à un utilisateur. C’est la brique qui permet de faire vivre la relation 0..1 entre users et bracelets.

### Mesures

POST /api/datas
GET /api/datas/{userId}
GET /api/statistics/{userId}

`POST /api/datas` reçoit un objet de mesure complet depuis le fake emitter ou l’app Android. `GET /api/datas/{userId}` liste les mesures d’un utilisateur, et `GET /api/statistics/{userId}` expose des agrégats simples.

## Contrat POST /api/datas

Champs attendus au minimum:

- `device_uid`
- `serial_number`

Champs recommandés:

- `display_name`
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