#!/bin/bash

# Enter location for cwa repo files below
REPO_DIR="/home/cwa-repo-download"
# Enter your DockerHub username here
DH_USER="crocodilestick"

rm -r -f $REPO_DIR
git clone http://github.com/crocodilestick/calibre-web-automated.git $REPO_DIR
cd $REPO_DIR

echo
echo Enter Version Number\: \(Convention is e.g. V2.0.1\)
read version

echo Dev or Production Image? Enter \'dev\' or \'prod\' to choose:
while true ; do
  read type
  case $type in
    dev | Dev | DEV)
      type="dev"
      echo Enter test version number\:
      read testnum
      break
      ;;

    prod | Prod | PROD)
      type="prod"
      break
      ;;

    *)
      echo Invalid entry. Please try again.
      ;;
  esac
done

NOW="$(date +"%Y-%m-%d %H:%M:%S")"

if [ type == "dev" ]; then
  docker build --tag $DH_USER/calibre-web-automated:dev --build-arg="BUILD_DATE=$NOW" --build-arg="VERSION=$version-TEST-$testnum" .
  echo
  echo "Dev image Version $version - Test $testnum created! Exiting now... "
else
  docker build --tag $DH_USER/calibre-web-automated:$version --build-arg="BUILD_DATE=$NOW" --build-arg="VERSION=$version" .
  echo
  echo "Prod image Version $version created! Exiting now..."
fi

cd
