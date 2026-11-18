Feature: Current grade on the course page
  As an enrolled student, I want to see my current grade at the top of each course page,
  so that I know how I'm doing without opening Canvas.

  Scenario Outline: Course page shows my current grade
    Given Canvas has my current grade for a course as <grade>
    When I open that course
    Then my grade reads "<shown>"

    Examples:
      | grade                  | shown                     |
      | 97.41 with no letter   | Current grade: 97.41%     |
      | 95.69 with letter A    | Current grade: 95.69% (A) |
      | 0 with no letter       | Current grade: 0%         |
      | letter A with no score | Current grade: A          |

  Scenario: Nothing graded yet
    Given nothing in my course has been graded yet
    When I open that course
    Then my grade reads "Current grade: No grade yet"

  Scenario: Instructor hides the course total
    Given my instructor hides the course total
    When I open that course
    Then my grade reads "Your instructor isn't showing a course total"

  Scenario: Canvas can't send my grade
    Given Canvas can't send my grade right now
    When I open that course
    Then my grade reads "Unable to load your current grade. Please try again."
    And I see the syllabus with its headings, lists, and tables
