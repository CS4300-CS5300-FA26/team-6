Feature: Landing page for logged-out visitors

  Scenario: Logged-out visitor sees the landing page
    Given I am not logged in
    And an assignment titled "Private Homework" exists
    When I open the homepage
    Then I see "Canvas+"
    And I see a login form
    And the "Register" link points to the registration page
    And I do not see "Private Homework"

  Scenario: Logged-in user skips the landing page
    Given I am logged in
    When I open the homepage
    Then I am taken to my logged-in home page

  Scenario: Logging in from the homepage
    Given I have an account
    When I log in with valid credentials using the form on the homepage
    Then I end up on my logged-in home page

  Scenario Outline: Failed login from the homepage
    Given I have an account
    When I log in from the homepage with <problem>
    Then I am on the login page with the message "Please enter a correct username and password"
    And I am still logged out

    Examples:
      | problem             |
      | the wrong password  |
      | an unknown username |
