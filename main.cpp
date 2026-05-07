#include<iostream>
#include<fstream>
#include<cstdlib>
#include<string>

using namespace std;

void ShowRandMM() {
     // randomly display a megaman character
     // access the characters from a data structure / file / folder
     string mm_sprites_path = "/mm-sprites/"; // --
     ofstream sprites;
     // current idea - for loop through sprites dir, select a random sprite and display it

}

void DisplayList() {
     // print a list of all the characters available
     // get the file name of each sprite, remove file extenstion

}



void Help() {

    int option;
    cout<<"***************************************************************************"<<endl;
    cout<<"*                               HELP MENU                                 *"<<endl;
    cout<<"***************************************************************************"<<endl;
    cout<< "   "<<endl;
    cout<< "Please choose an option"<<endl;
    cout<< "1. Randomly display a Mega Man X character  "<<endl;
    cout<< "2. List of all available Mega Man X Characters " <<endl;
    cout<< "3. Exit" << endl;
    cin >> option;


    switch(option) {
         case 1:
            // some logic

         case 2:
            // some logic
            //

         case 3:
              break;

    }
}


int main() {

cout << " Megaman CLI -- display Megaman sprites on your terminal  " <<endl;



return 0;
}
