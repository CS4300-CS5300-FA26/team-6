Feature: Personal calendar subscriptions
  As an enrolled college student
  I want a private calendar subscription URL for my coursework schedule
  So that I can view assignment deadlines and planned study sessions in my calendar application

  Scenario: I create and rotate my personal calendar URL
    Given I am signed in to Canvas Plus as a student
    When I create a calendar subscription in account settings
    Then I receive a personal calendar URL
    And the URL is shown only in the creation response
    When I rotate my calendar subscription
    Then the new URL differs and the previous URL is revoked

  Scenario: My calendar feed shows assignment deadlines and study sessions
    Given my account has a due-dated assignment and a saved study session
    When a calendar client requests my feed
    Then the feed contains a point deadline with its assignment and course
    And the feed contains a timed study session with its assignment and course
    And the feed excludes another student's coursework

  Scenario: I can subscribe before eligible coursework events exist
    Given I have an active subscription and no eligible coursework events
    When a calendar client requests my feed
    Then I receive a valid calendar with no events