Feature: Search assignments by keyword
  As an enrolled college student
  I want to search across assignments in all my courses
  So that I can find a specific assignment without opening each course

  Scenario: Keyword matches an assignment title
    Given my Canvas assignment index contains "Lab 3: Recursion" in course "CS 4300"
    When I search assignments for "recursion"
    Then I see "Lab 3: Recursion" in the assignment search results
    And I see course "CS 4300" in the assignment search results
    And the assignment result opens Canvas in a new tab

  Scenario: Keyword matches an assignment description
    Given my assignment "Essay 1" has description "Follow the provided rubric carefully"
    When I search assignments for "rubric"
    Then I see "Essay 1" in the assignment search results

  Scenario: No assignment matches the keyword
    Given my assignment index does not contain "zebra"
    When I search assignments for "zebra"
    Then I see no assignment results for "zebra"

  Scenario: Empty assignment search
    Given I am on the assignment search page
    When I search assignments without entering a term
    Then I am prompted to enter a search term