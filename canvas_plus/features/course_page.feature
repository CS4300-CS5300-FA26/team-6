Feature: Course page with syllabus
  As an enrolled college student, I want to open a page for each of my courses that shows
  its syllabus, so that I can read course policies and expectations without digging through Canvas.

  Scenario: Course has a syllabus
    Given my course has a syllabus with headings, lists, and tables
    When I select that course from my course list
    Then I see a page titled with the course name
    And I see the syllabus with its headings, lists, and tables
    And I can go back to my course list

  Scenario: Syllabus mentions a file
    Given my course syllabus links to a file in Canvas
    When I open that course
    Then I see the file's name
    And I see "Files in this syllabus"
    And nothing on the page takes me to Canvas

  Scenario Outline: No syllabus posted
    Given my course has <syllabus>
    When I open that course
    Then I see "No syllabus posted in Canvas for this course"

    Examples:
      | syllabus              |
      | no syllabus in Canvas |
      | a blank syllabus      |

  Scenario: Syllabus contains unsafe content
    Given a course syllabus in Canvas contains a script
    When I open that course
    Then I see the syllabus text
    And the script does not run

  Scenario Outline: Course page can't be shown
    Given <situation>
    When I open that course
    Then I see "<message>"

    Examples:
      | situation                        | message          |
      | I am not enrolled in that course | Course not found |
      | Canvas is down                   | Please try again |
