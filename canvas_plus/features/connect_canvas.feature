Feature: Connect a student's Canvas account
  As an enrolled college student
  I want to connect Canvas using a personal access token
  So that Canvas+ can load my courses and coursework

  Scenario: Student connects with a valid token
    Given I am on the "Connect Canvas" page
    When I paste a valid Canvas personal access token and click "Connect"
    Then I see "Canvas connected"
    And I see a list of my enrolled course names

  Scenario: Student enters an invalid token
    Given I am on the "Connect Canvas" page
    When I paste an invalid token and click "Connect"
    Then I see "Invalid token. Check your token and try again."
    And I remain on the "Connect Canvas" page

  Scenario: Student's saved token stops working
    Given I previously connected my Canvas account
    And my token has since been deleted or has expired in Canvas
    When I open the app
    Then I see "Your Canvas connection expired. Please reconnect."
    And I see a link to the "Connect Canvas" page

  Scenario: Saved token is not displayed in full
    Given I have connected my Canvas account
    When I open the "Connect Canvas" page
    Then I see only the last 4 characters of my saved token
    And the rest of the token is hidden
