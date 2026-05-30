# Mail Subscription System — Logs

## Loki / Alloy integration

Application monitor logs are written to systemd journal by `mailsub-monitor.service`.
To query web/frontend health events in Grafana Loki, install Alloy on `mail1`,
`mail2`, and `mail3` and collect that service's journal logs.

Useful Loki queries:

```logql
{unit="mailsub-monitor.service"} |= "serving_health_down"
```

```logql
{unit="mailsub-monitor.service"} |= "\"service\":\"web\"" |= "serving_health_down"
```

```logql
{unit="mailsub-monitor.service"} |= "\"service\":\"frontend\"" |= "serving_health_down"
```

Monitor log messages are JSON objects with fields such as `level`, `logger`,
`event`, `message`, `service`, `check`, `target`, and `error`.

## Legacy rsyslog collection

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
