# How to get started with the project

### Set up the python virtual environment and 

execute the bash file for setting up the environment and download all the packages
```sh
    cd webapp
    source setup.sh
```

### Launch the web service
The following command create a Sqlite database, because Django requires several intern applications and migrate all of them.
The second command launch the deploiement server in a local web app. It is accessible through `localhost:8000/api/<route>`

```sh
python3 manage.py migrate         # applies DB migrations
python3 manage.py check           # "check" — Django's system check framework (settings, models, urls)
python3 manage.py test            # runs api/tests.py (currently just the empty TestCase scaffold)

```



