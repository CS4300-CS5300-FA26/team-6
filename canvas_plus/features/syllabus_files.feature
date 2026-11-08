Feature: Preview syllabus files on the course page
  As a student, I want to preview the PDFs my syllabus links to right on the course page,
  so that I can read them without going back to Canvas.

  Scenario: Preview a PDF
    Given my course syllabus links to a PDF in Canvas
    When I open that course and expand the file
    Then I see the PDF on the course page

  Scenario: File type that can't be previewed
    Given my course syllabus links to a Word file in Canvas
    When I open that course
    Then I can download the Word file from the syllabus
    And downloading it doesn't take me to Canvas

  Scenario: File too large to preview
    Given my course syllabus links to a PDF over 25 MB
    When I expand the file
    Then I see "This file is too large to preview"
    And I can download it without going to Canvas

  Scenario: File can't be loaded
    Given a linked file was deleted, is locked by my professor, or Canvas is down
    When I expand the file
    Then I see "This file couldn't be loaded. Please try again."
    And the rest of the course page still shows

  Scenario: File from a course that isn't mine
    Given a file belongs to a course not in my current list
    When I try to open it
    Then I see "File not found"
    And Canvas is never asked for it
