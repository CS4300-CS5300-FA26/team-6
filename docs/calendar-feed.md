# Calendar feed

Canvas Plus provides a private, read-only iCalendar subscription for a student's
assignment deadlines and saved study sessions. The feed is generated from current
local records whenever a calendar client requests it; generating the feed does
not make a request to Canvas.

## Create or rotate a subscription URL

Sign in and open [Account settings](/accounts/settings/). Under Calendar
subscription, choose **Create subscription URL**. Copy the URL shown in the
successful response and add it to your calendar application using its
subscription or internet-calendar option. The URL is displayed only in that
response and is not shown on later visits to settings. If it is lost, create a
new URL by choosing **Rotate subscription URL**.

Rotating replaces the subscription credential immediately, so the previous URL
can no longer fetch the feed. A calendar client may continue to display events
it downloaded earlier until it refreshes or removes its cached copy.

## Keep the URL private

The URL contains a high-entropy bearer credential: anyone who has it can read
the feed without signing in. Treat it like a password. Do not post or send it in
public, and use HTTPS when subscribing, especially on shared networks. If you
think the URL has been exposed, rotate it in account settings. The previous URL
will stop working for new requests, but rotation cannot erase data already
downloaded or cached by a calendar provider.

Canvas Plus stores only a SHA-256 digest of the credential, not the original
secret. The feed is read-only and does not let a calendar client change
assignments, study plans, or sessions. The feed endpoint does not require a
Canvas Plus login; possession of the active URL is the authorization.

## Included events and retention

The feed includes each of the account's assignments that has a due date, and
study sessions in all of the account's saved plans. Assignment events use the
stored due instant and are point events. Session events include their start and
end instants. Event titles contain the assignment and course names; descriptions
are omitted. Dates are serialized using the configured Django `TIME_ZONE`,
including timezone transitions such as daylight saving time.

Events are included while their assignment due time or session end time is
strictly later than the retention cutoff. The cutoff is the current time minus
`CALENDAR_FEED_RETENTION_DAYS`; its default is `112`. This is elapsed-day
retention, not a calendar-date boundary. Future events are not capped by this
setting. To change the retention period, configure a nonnegative integer value
for `CALENDAR_FEED_RETENTION_DAYS` in Django settings and deploy the change.

## Refresh and caching

Canvas Plus generates the feed from current local data on each request and marks
its HTTP response as non-cacheable. Calendar applications control when they
request updates and how long they keep downloaded data. Their refresh intervals
and cache-removal behavior vary; Canvas Plus cannot force a refresh or guarantee
that rotating a URL immediately removes previously downloaded events from a
client.