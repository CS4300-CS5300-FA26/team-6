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
