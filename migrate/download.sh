rm bulkloader-*
rm *.csv
rm *.json

#appcfg.py create_bulkloader_config --secure --email=csytan@gmail.com --application=s~vittyo-app --url=http://vittyo-app.appspot.com/_ah/remote_api --filename=config.yml

models=( "User" "Counter" "Video" "Comment" "Feed" )
for model in "${models[@]}"
do
    appcfg.py download_data --secure --email=csytan@gmail.com --application=s~vittyo-app --url=http://vittyo-app.appspot.com/_ah/remote_api --config_file=config.yml --filename=$model.csv --kind=$model
    python csv2json.py $model.csv
done

#rethinkdb import -c localhost:28015 --table nohuck.videos -f Video.csv.json --format json
