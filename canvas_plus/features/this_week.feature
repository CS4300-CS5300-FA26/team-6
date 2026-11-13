Feature: This Week on the dashboard
  As an enrolled college student
  I want to see this week's assignments organized by day on my dashboard
  So that I can plan my workload alongside upcoming assignments and recent grades

  Scenario: Student views the week at a glance
    Given I am a student with a connected Canvas account
    And I have an assignment "HW3" due this Tuesday
    And I have an assignment "Lab 4" due this Friday
    And I have an assignment "Quiz 2" due this Friday
    When I navigate to the main dashboard
    Then I see a This Week section with columns for Monday through Sunday
    And This Week shows "HW3" on Tuesday
    And This Week shows "Lab 4" on Friday
    And This Week shows "Quiz 2" on Friday

  Scenario: Dashboard layout matches the wireframe
    Given I am a student with a connected Canvas account
    When I navigate to the main dashboard
    Then I see Upcoming Assignments, then Recently Graded, then the This Week calendar

  Scenario: A day has no assignments
    Given I am a student with a connected Canvas account
    And I have an assignment "HW3" due this Tuesday
    And I have no assignments due this Saturday
    When I navigate to the main dashboard
    Then This Week shows Saturday with no assignments

  Scenario: Assignments outside this week are not shown
    Given I am a student with a connected Canvas account
    And I have an assignment "Old Lab" due last Sunday
    And I have an assignment "Next Quiz" due next Monday
    When I navigate to the main dashboard
    Then This Week does not show "Old Lab"
    And This Week does not show "Next Quiz"

  # In UTC, which is how Canvas sends times, both deadlines fall on Monday.
  Scenario: Late Sunday and early Monday deadlines stay on their own days
    Given I am a student with a connected Canvas account
    And I have an assignment "Late Essay" due at 11:30 PM this Sunday
    And I have an assignment "Early Quiz" due at 12:30 AM next Monday
    When I navigate to the main dashboard
    Then This Week shows "Late Essay" on Sunday
    And This Week does not show "Early Quiz"

  # Abuse case: assignments belong to one student and never leak onto another's week.
  Scenario: Another student's assignments never appear
    Given I am a student with a connected Canvas account
    And I have an assignment "HW3" due this Wednesday
    And another student has an assignment "Their Project" due this Wednesday
    When I navigate to the main dashboard
    Then This Week shows "HW3" on Wednesday
    And This Week does not show "Their Project"

  Scenario: An assignment removed from Canvas is not shown
    Given I am a student with a connected Canvas account
    And I have an assignment "HW3" due this Thursday
    And an assignment "Dropped Lab" due this Thursday was removed from Canvas
    When I navigate to the main dashboard
    Then This Week shows "HW3" on Thursday
    And This Week does not show "Dropped Lab"

  Scenario: An assignment without a due date is not placed on a day
    Given I am a student with a connected Canvas account
    And I have an assignment "Optional Reading" with no due date
    When I navigate to the main dashboard
    Then This Week does not show "Optional Reading"

  # An empty or stale week would wrongly tell the student what is due.
  # The outage step sets up its own connected student, so it comes first.
  Scenario: This Week cannot be loaded while Canvas is down
    Given Canvas is temporarily unavailable while loading assignments
    When I navigate to the main dashboard
    Then I am told This Week cannot be loaded right now

  Scenario: This Week cannot be loaded when the assignment sync fails
    Given I am a student with a connected Canvas account
    And syncing my Canvas assignments fails
    When I navigate to the main dashboard
    Then I am told This Week cannot be loaded right now

  # Without a connection there is nothing to show, and an empty week would mislead.
  Scenario: Student without a Canvas connection does not see an empty week
    Given I am a signed-in student without a Canvas connection
    When I navigate to the main dashboard
    Then I do not see the This Week calendar

  Scenario: Student with an expired Canvas connection does not see an empty week
    Given my saved Canvas token is rejected while loading assignments
    When I navigate to the main dashboard
    Then I do not see the This Week calendar
