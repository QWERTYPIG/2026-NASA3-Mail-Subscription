# Mail Subscription System — Logs
logs are stored at `/var/log/mailsub-stack.log` on each machine (mail1~3)
need to run 
```
sudo touch /var/log/mailsub-stack.json
sudo chown syslog:adm /var/log/mailsub-stack.json
sudo chmod 640 /var/log/mailsub-stack.json
```
and add this file `/etc/rsyslog.d/30-docker-mailsub.conf`
with content
```
template(name="DockerJSON" type="string" string="{\"timestamp\":\"%timereported:::date-rfc3339%\", \"container\":\"%syslogtag%\", \"message\":\"%msg:::json%\"}\n")
if $programname startswith 'docker-mailsub' or $syslogtag startswith 'docker-mailsub' then {
    action(type="omfile" file="/var/log/mailsub-stack.json" template="DockerJSON")
    stop
}
```
and restart service `sudo systemctl restart rsyslog`
