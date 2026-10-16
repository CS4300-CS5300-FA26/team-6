Feature: Assignments page

  Scenario: Assignments page loads
    Given the assignments page exists
    When I request the assignments page
    Then the assignments page loads successfully

#verifys behave uses Django test DB
  Scenario: Behave uses a test database
    Given I create a test assignment
    Then the test assignment exists in the database
    