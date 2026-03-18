# SaveMyExams Composer

A tool to compose exam paper from screenshots.

[SaveMyExams](https://www.savemyexams.com/) is a popular platform to learn standardized tests. While the website provides comprehensive feature on composing testing papers, you cannot directly collect all your mistaken problems in a mock exam and compose them into a standalone paper. You may also want to save the paper offline, so they are present even after the expiration of your SME subscription.

Therefore, SaveMyExams Composer is created. It automatically arranges the screenshots you take from SME into printable PDF paper.

## Usage

1. Take **PNG** screenshots of the answer page (it already contains the problem)
2. Save all PNGs into a folder
3. ```bash
   python main.py
   ```
4. Enter the path to the folder
5. Done! Problem paper and answer paper will both be generated automatically

## How does it work

It is actually very simple. Anything below "You answered" is the answer. So the script find that line using fuzzy OCR then crop the image.

## License

[MIT License](./LICENSE). Feel free to modify this repo as you wish!
