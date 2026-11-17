Feature: Personal calendar subscriptions
  Scenario: A student issues, copies, and rotates a private feed URL
    When I issue, copy, and rotate a personal subscription URL

  Scenario: A student fetches assignment and study-session events
    When I fetch assignment and study-session events from local records

  Scenario: A student subscribes before any events exist
    When I subscribe to a valid empty calendar feed using local records