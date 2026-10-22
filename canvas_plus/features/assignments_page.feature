Feature: Assignments page

  Scenario: A student sees upcoming coursework and its due date
    Given I am a connected student with upcoming coursework due on "October 22, 2026 at 12:30 PM"
    When I open the logged-in home page
    Then I see "Canvas Project 1" for "CS 4300" due "Oct 22, 2026 12:30 PM"

  Scenario: A student sees the agreed empty state
    Given I am a connected student with no upcoming coursework
    When I open the logged-in home page
    Then I see exactly "No upcoming assignments"

  Scenario: A revised Canvas due date appears after reload
    Given I am viewing "Canvas Project 1" for "CS 4300" due "Oct 22, 2026 12:30 PM"
    When Canvas changes its due date to "October 24, 2026 at 12:30 PM"
    And I reload the logged-in home page
    Then I see the revised due date "Oct 24, 2026 12:30 PM" instead of "Oct 22, 2026 12:30 PM"

  Scenario: A student without a Canvas connection is prompted to connect
    Given I am a signed-in student without a Canvas connection
    When I open the logged-in home page
    Then I see the Canvas connection prompt instead of the empty state

  Scenario: An expired Canvas token prompts the student to reconnect
    Given my saved Canvas token is rejected while loading assignments
    When I open the logged-in home page
    Then I see the expired Canvas connection message and reconnect link

  Scenario: A temporary Canvas failure is not shown as an empty result
    Given Canvas is temporarily unavailable while loading assignments
    When I open the logged-in home page
    Then I see the assignments unavailable message instead of the empty state

  Scenario: Work due within 48 hours is flagged as due soon
    Given I am a connected student with unsubmitted coursework due in 30 hours
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Due soon"

  Scenario: Work with ample time is not flagged as high priority
    Given I am a connected student with unsubmitted coursework due in 6 days
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Upcoming"
    And I see no high-priority marker

  Scenario: The marker escalates once the deadline window is entered
    Given I am a connected student with unsubmitted coursework due in 50 hours
    And my dashboard shows "Canvas Project 1" marked "Upcoming"
    When 3 hours pass
    And I reload the logged-in home page
    Then I see "Canvas Project 1" marked "Due soon"

  Scenario: A missed deadline shows a past-due warning
    Given I am a connected student with unsubmitted coursework that was due 2 hours ago
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Past due"

  Scenario: Submitted work is not flagged as urgent
    Given I am a connected student who has submitted coursework due in 30 hours
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Submitted"
