!#/bin/bash

platform=`awk -F= '/^NAME/{print $2}' /etc/os-release`
echo $platform

if [ "\"Ubuntu\"" = "${platform}" ]; then
    echo "it is ubuntu"

    # install and run redis server
    sudo apt install -y redis-server
    sudo systemctl enable redis.service
    sudo systemctl start redis.service

    echo "install python-pip python-devel ..."
    sudo apt install -y python-pip python-dev python3-pip

    echo "install wsgi flask ..."
    # should install flask to ~/.local/lib/python3.6/site-packages
    pip3 install flask redis

elif [ "\"CentOS Linux\"" = "${platform}" ]; then
    echo "it is CentOS"

    echo "install epel-release ..."
    sudo yum install -y epel-release yum-utils

    # install and run redis server
    sudo yum install -y redis
    sudo systemctl enable redis.service
    sudo systemctl start redis.service

    echo "install python-pip python-devel ..."
    sudo yum install -y python-pip python-devel

    echo "install flask ..."
    sudo pip install flask redis
fi
